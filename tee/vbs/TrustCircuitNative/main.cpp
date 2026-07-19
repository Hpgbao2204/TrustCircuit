#include <Windows.h>
#include <bcrypt.h>

#include "..\Shared\DatasetAggregate.h"
#include "..\TrustCircuitHost\Json.h"

#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <intrin.h>
#include <iostream>
#include <limits>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace
{
const auto processStarted = std::chrono::steady_clock::now();

constexpr std::size_t sha256DigestBytes = 32;
constexpr std::size_t aes256KeyBytes = 32;
constexpr std::size_t gcmNonceBytes = 12;
constexpr std::size_t gcmTagBytes = 16;
constexpr std::size_t maxIdentifierBytes = 128;
constexpr std::size_t maxPayloadPathBytes = 1024;
constexpr std::size_t maxAadBytes = 4096;
constexpr std::size_t maxEncryptedPayloadBytes =
    trustcircuit::processing::datasetHeaderBytes +
    static_cast<std::size_t>(trustcircuit::processing::maxDatasetRows) *
        sizeof(std::int64_t);
constexpr std::uint8_t requestDomain[] = "TrustCircuit.Request.v1";
constexpr std::uint8_t resultDomain[] = "TrustCircuit.Result.v1";
constexpr std::uint8_t transcriptDomain[] = "TrustCircuit.Execution.v1";
constexpr std::uint8_t nativeIdentityDomain[] =
    "TrustCircuit.NativeProcessor.v1";
constexpr long double epsilonFixedScale = 1000000.0L;
constexpr long double deltaFixedScale = 1000000000000.0L;
constexpr long double twoPi =
    6.283185307179586476925286766559005768L;

struct ExecutionRequest
{
    std::string requestId;
    std::string assetId;
    std::string consumerId;
    std::string policyHash;
    std::uint64_t policyVersion{};
    std::uint32_t functionId{};
    long double epsilonRequested{};
    long double deltaRequested{};
    std::uint64_t epsilonRequestedFixed{};
    std::uint64_t deltaRequestedFixed{};
    std::string encryptedPayloadPath;
    std::vector<std::uint8_t> key;
    std::vector<std::uint8_t> nonce;
    std::vector<std::uint8_t> authenticationTag;
    std::vector<std::uint8_t> aad;
    std::vector<std::uint8_t> expectedDataHash;
    std::int64_t lowerBoundFixed{};
    std::int64_t upperBoundFixed{};
    std::uint64_t deadlineUnixMs{};
    bool applyDp{};
};

class SecureBuffer
{
public:
    explicit SecureBuffer(std::size_t size) : bytes(size) {}
    explicit SecureBuffer(const std::vector<std::uint8_t>& source)
        : bytes(source)
    {
    }
    ~SecureBuffer()
    {
        SecureZeroMemory(bytes.data(), bytes.size());
    }
    SecureBuffer(const SecureBuffer&) = delete;
    SecureBuffer& operator=(const SecureBuffer&) = delete;
    std::vector<std::uint8_t> bytes;
};

class BCryptHash
{
public:
    ~BCryptHash()
    {
        if (value != nullptr)
        {
            BCryptDestroyHash(value);
        }
    }
    BCRYPT_HASH_HANDLE value{};
};

class BCryptKey
{
public:
    ~BCryptKey()
    {
        if (value != nullptr)
        {
            BCryptDestroyKey(value);
        }
    }
    BCRYPT_KEY_HANDLE value{};
};

void appendUint32LittleEndian(
    std::vector<std::uint8_t>& output,
    std::uint32_t value)
{
    for (std::size_t index = 0; index < sizeof(value); ++index)
    {
        output.push_back(static_cast<std::uint8_t>(value >> (index * 8)));
    }
}

void appendUint64LittleEndian(
    std::vector<std::uint8_t>& output,
    std::uint64_t value)
{
    for (std::size_t index = 0; index < sizeof(value); ++index)
    {
        output.push_back(static_cast<std::uint8_t>(value >> (index * 8)));
    }
}

void appendInt64LittleEndian(
    std::vector<std::uint8_t>& output,
    std::int64_t value)
{
    appendUint64LittleEndian(output, static_cast<std::uint64_t>(value));
}

void appendBytes(
    std::vector<std::uint8_t>& output,
    std::span<const std::uint8_t> value)
{
    output.insert(output.end(), value.begin(), value.end());
}

void appendSizedString(
    std::vector<std::uint8_t>& output,
    const std::string& value)
{
    appendUint32LittleEndian(output, static_cast<std::uint32_t>(value.size()));
    output.insert(output.end(), value.begin(), value.end());
}

bool constantTimeEqual(
    std::span<const std::uint8_t> left,
    std::span<const std::uint8_t> right)
{
    if (left.size() != right.size())
    {
        return false;
    }
    std::uint8_t difference = 0;
    for (std::size_t index = 0; index < left.size(); ++index)
    {
        difference |= left[index] ^ right[index];
    }
    return difference == 0;
}

bool isLowerHex(const std::string& value)
{
    return std::all_of(value.begin(), value.end(), [](char character) {
        return (character >= '0' && character <= '9') ||
            (character >= 'a' && character <= 'f');
    });
}

HRESULT sha256(
    std::span<const std::uint8_t> input,
    std::vector<std::uint8_t>& digest)
{
    BCryptHash hash;
    NTSTATUS status = BCryptCreateHash(
        BCRYPT_SHA256_ALG_HANDLE,
        &hash.value,
        nullptr,
        0,
        nullptr,
        0,
        0);
    if (status < 0)
    {
        return HRESULT_FROM_NT(status);
    }
    if (!input.empty())
    {
        status = BCryptHashData(
            hash.value,
            const_cast<PUCHAR>(input.data()),
            static_cast<ULONG>(input.size()),
            0);
        if (status < 0)
        {
            return HRESULT_FROM_NT(status);
        }
    }
    digest.assign(sha256DigestBytes, 0);
    status = BCryptFinishHash(
        hash.value,
        digest.data(),
        static_cast<ULONG>(digest.size()),
        0);
    return status < 0 ? HRESULT_FROM_NT(status) : S_OK;
}

std::vector<std::uint8_t> buildCanonicalAad(
    const ExecutionRequest& request)
{
    std::vector<std::uint8_t> canonical;
    canonical.reserve(512 + request.encryptedPayloadPath.size());
    appendBytes(canonical, requestDomain);
    appendSizedString(canonical, request.requestId);
    appendSizedString(canonical, request.assetId);
    appendSizedString(canonical, request.consumerId);
    appendSizedString(canonical, request.policyHash);
    appendSizedString(canonical, request.encryptedPayloadPath);
    appendBytes(canonical, request.expectedDataHash);
    appendUint64LittleEndian(canonical, request.policyVersion);
    appendUint32LittleEndian(canonical, request.functionId);
    appendUint64LittleEndian(canonical, request.epsilonRequestedFixed);
    appendUint64LittleEndian(canonical, request.deltaRequestedFixed);
    appendInt64LittleEndian(canonical, request.lowerBoundFixed);
    appendInt64LittleEndian(canonical, request.upperBoundFixed);
    appendUint64LittleEndian(canonical, request.deadlineUnixMs);
    canonical.push_back(request.applyDp ? 1 : 0);
    return canonical;
}

HRESULT addGaussianNoise(
    std::uint32_t functionId,
    std::uint64_t rows,
    std::int64_t lowerBoundFixed,
    std::int64_t upperBoundFixed,
    std::uint64_t epsilonRequestedFixed,
    std::uint64_t deltaRequestedFixed,
    std::int64_t& resultFixed,
    std::uint64_t& actualPrivacyCostFixed)
{
    using namespace trustcircuit::processing;
    if (epsilonRequestedFixed == 0 ||
        epsilonRequestedFixed > static_cast<std::uint64_t>(epsilonFixedScale) ||
        deltaRequestedFixed == 0 ||
        deltaRequestedFixed >= static_cast<std::uint64_t>(deltaFixedScale) ||
        (functionId == functionMean && rows == 0))
    {
        return E_INVALIDARG;
    }

    const auto epsilon =
        static_cast<long double>(epsilonRequestedFixed) / epsilonFixedScale;
    const auto delta =
        static_cast<long double>(deltaRequestedFixed) / deltaFixedScale;
    const auto sensitivityFixed = functionId == functionCount
        ? static_cast<long double>(fixedPointScale)
        : (static_cast<long double>(upperBoundFixed) -
           static_cast<long double>(lowerBoundFixed)) /
              static_cast<long double>(rows);
    const auto noiseMultiplier =
        std::sqrt(2.0L * std::log(1.25L / delta)) / epsilon;

    std::uint64_t randomValues[2]{};
    const auto randomStatus = BCryptGenRandom(
        nullptr,
        reinterpret_cast<PUCHAR>(randomValues),
        sizeof(randomValues),
        BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (randomStatus < 0)
    {
        return HRESULT_FROM_NT(randomStatus);
    }
    const auto denominator =
        static_cast<long double>((std::numeric_limits<std::uint64_t>::max)()) +
        2.0L;
    const auto uniformOne =
        (static_cast<long double>(randomValues[0]) + 1.0L) / denominator;
    const auto uniformTwo =
        (static_cast<long double>(randomValues[1]) + 1.0L) / denominator;
    const auto standardNormal =
        std::sqrt(-2.0L * std::log(uniformOne)) *
        std::cos(twoPi * uniformTwo);
    const auto noisyResult = static_cast<long double>(resultFixed) +
        standardNormal * sensitivityFixed * noiseMultiplier;
    if (!std::isfinite(noisyResult) ||
        noisyResult < static_cast<long double>(
            (std::numeric_limits<std::int64_t>::min)()) ||
        noisyResult > static_cast<long double>(
            (std::numeric_limits<std::int64_t>::max)()))
    {
        return HRESULT_FROM_WIN32(ERROR_ARITHMETIC_OVERFLOW);
    }
    resultFixed = static_cast<std::int64_t>(std::llround(noisyResult));

    auto minimumRdpEpsilon =
        (std::numeric_limits<long double>::infinity)();
    for (std::uint32_t alpha = 2; alpha <= 64; ++alpha)
    {
        const auto alphaValue = static_cast<long double>(alpha);
        const auto rdp = alphaValue /
            (2.0L * noiseMultiplier * noiseMultiplier);
        const auto converted = rdp +
            std::log(1.0L / delta) / (alphaValue - 1.0L);
        minimumRdpEpsilon = (std::min)(minimumRdpEpsilon, converted);
    }
    const auto conservativeEpsilon =
        (std::max)(minimumRdpEpsilon, epsilon);
    const auto conservativeFixed =
        std::ceil(conservativeEpsilon * epsilonFixedScale);
    if (!std::isfinite(conservativeFixed) || conservativeFixed < 0 ||
        conservativeFixed > static_cast<long double>(
            (std::numeric_limits<std::uint64_t>::max)()))
    {
        return HRESULT_FROM_WIN32(ERROR_ARITHMETIC_OVERFLOW);
    }
    actualPrivacyCostFixed = static_cast<std::uint64_t>(conservativeFixed);
    return S_OK;
}

std::vector<std::uint8_t> loadBinaryFile(const std::filesystem::path& path)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream)
    {
        throw std::runtime_error("cannot open input file");
    }
    const auto end = stream.tellg();
    if (end < 0 || static_cast<std::uint64_t>(end) > 2ULL * 1024ULL * 1024ULL)
    {
        throw std::runtime_error("input file is too large");
    }
    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    if (!bytes.empty() &&
        !stream.read(reinterpret_cast<char*>(bytes.data()), end))
    {
        throw std::runtime_error("cannot read input file");
    }
    return bytes;
}

std::string loadTextFile(const std::filesystem::path& path)
{
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream)
    {
        throw std::runtime_error("cannot open request JSON");
    }
    const auto end = stream.tellg();
    if (end < 0 || end > 64 * 1024)
    {
        throw std::runtime_error("request JSON is too large");
    }
    std::string value(static_cast<std::size_t>(end), '\0');
    stream.seekg(0, std::ios::beg);
    if (!value.empty() && !stream.read(value.data(), end))
    {
        throw std::runtime_error("cannot read request JSON");
    }
    return value;
}

std::uint8_t decodeHexNibble(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    throw std::runtime_error("malformed hexadecimal input");
}

std::vector<std::uint8_t> decodeHex(const std::string& value)
{
    if ((value.size() % 2) != 0)
    {
        throw std::runtime_error("malformed hexadecimal input");
    }
    std::vector<std::uint8_t> decoded(value.size() / 2);
    for (std::size_t index = 0; index < decoded.size(); ++index)
    {
        decoded[index] = static_cast<std::uint8_t>(
            (decodeHexNibble(value[index * 2]) << 4) |
            decodeHexNibble(value[index * 2 + 1]));
    }
    return decoded;
}

std::string encodeHex(const std::vector<std::uint8_t>& value)
{
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (const auto byte : value)
    {
        output << std::setw(2) << static_cast<unsigned int>(byte);
    }
    return output.str();
}

std::uint64_t calibrateTscTicksPerMicrosecond()
{
    LARGE_INTEGER frequency{};
    LARGE_INTEGER started{};
    LARGE_INTEGER current{};
    if (!QueryPerformanceFrequency(&frequency) || frequency.QuadPart <= 0 ||
        !QueryPerformanceCounter(&started))
    {
        throw std::runtime_error("cannot calibrate stage timer");
    }
    const auto startedTsc = __rdtsc();
    const auto targetQpcTicks = frequency.QuadPart / 200;
    do
    {
        if (!QueryPerformanceCounter(&current))
        {
            throw std::runtime_error("cannot calibrate stage timer");
        }
    } while (current.QuadPart - started.QuadPart < targetQpcTicks);
    const auto elapsedQpc = current.QuadPart - started.QuadPart;
    const auto elapsedTsc = __rdtsc() - startedTsc;
    const auto ticksPerMicrosecond = static_cast<std::uint64_t>(
        (static_cast<long double>(elapsedTsc) * frequency.QuadPart) /
        (static_cast<long double>(elapsedQpc) * 1000000.0L));
    return ticksPerMicrosecond == 0 ? 1 : ticksPerMicrosecond;
}

std::uint64_t currentUnixMilliseconds()
{
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
}

std::uint64_t elapsedMicroseconds(std::chrono::steady_clock::time_point started)
{
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now() - started).count());
}

ExecutionRequest parseRequest(const trustcircuit::json::Object& object)
{
    if (trustcircuit::json::requireString(object, "operation") != "execute")
    {
        throw std::runtime_error("unsupported JSON operation");
    }
    ExecutionRequest request;
    request.requestId = trustcircuit::json::requireString(object, "request_id");
    request.assetId = trustcircuit::json::requireString(object, "asset_id");
    request.consumerId = trustcircuit::json::requireString(object, "consumer_id");
    request.policyHash = trustcircuit::json::requireString(object, "policy_hash");
    request.policyVersion = trustcircuit::json::requireUint64(object, "policy_version");
    const auto functionId = trustcircuit::json::requireUint64(object, "function_id");
    if (functionId > (std::numeric_limits<std::uint32_t>::max)())
    {
        throw std::runtime_error("function_id is out of range");
    }
    request.functionId = static_cast<std::uint32_t>(functionId);
    request.epsilonRequested = trustcircuit::json::requireNumber(object, "epsilon_requested");
    request.deltaRequested = trustcircuit::json::requireNumber(object, "delta_requested");
    request.epsilonRequestedFixed = trustcircuit::json::requireUint64(object, "epsilon_requested_fixed");
    request.deltaRequestedFixed = trustcircuit::json::requireUint64(object, "delta_requested_fixed");
    request.encryptedPayloadPath = trustcircuit::json::requireString(object, "encrypted_payload_path");
    request.key = decodeHex(trustcircuit::json::requireString(object, "key_hex"));
    request.nonce = decodeHex(trustcircuit::json::requireString(object, "nonce"));
    request.authenticationTag = decodeHex(trustcircuit::json::requireString(object, "authentication_tag"));
    request.aad = decodeHex(trustcircuit::json::requireString(object, "aad"));
    request.expectedDataHash = decodeHex(trustcircuit::json::requireString(object, "data_hash"));
    request.lowerBoundFixed = trustcircuit::json::requireInt64(object, "lower_bound_fixed");
    request.upperBoundFixed = trustcircuit::json::requireInt64(object, "upper_bound_fixed");
    request.deadlineUnixMs = trustcircuit::json::requireUint64(object, "deadline_unix_ms");
    request.applyDp = trustcircuit::json::requireBoolean(object, "apply_dp");
    if (!std::isfinite(request.epsilonRequested) ||
        !std::isfinite(request.deltaRequested) ||
        request.epsilonRequested < 0 || request.deltaRequested < 0)
    {
        throw std::runtime_error("invalid privacy parameters");
    }
    if (!request.applyDp &&
        (request.epsilonRequestedFixed != 0 || request.deltaRequestedFixed != 0))
    {
        throw std::runtime_error("non-DP requests must use zero privacy parameters");
    }
    if (request.applyDp)
    {
        if (request.epsilonRequested <= 0 || request.epsilonRequested > 1.0L ||
            request.deltaRequested <= 0 || request.deltaRequested >= 1.0L)
        {
            throw std::runtime_error("DP parameters are outside supported bounds");
        }
        const auto expectedEpsilonFixed = static_cast<std::uint64_t>(
            std::ceil(request.epsilonRequested * epsilonFixedScale));
        const auto expectedDeltaFixed = static_cast<std::uint64_t>(
            std::ceil(request.deltaRequested * deltaFixedScale));
        if (request.epsilonRequestedFixed != expectedEpsilonFixed ||
            request.deltaRequestedFixed != expectedDeltaFixed)
        {
            throw std::runtime_error("privacy fixed-point fields are inconsistent");
        }
    }
    return request;
}

std::string formatFixed(std::int64_t value)
{
    const bool negative = value < 0;
    const auto magnitude = negative
        ? static_cast<std::uint64_t>(-(value + 1)) + 1
        : static_cast<std::uint64_t>(value);
    std::ostringstream output;
    if (negative) output << '-';
    output << magnitude / 1000000ULL << '.' << std::setw(6)
           << std::setfill('0') << magnitude % 1000000ULL;
    return output.str();
}

void check(HRESULT result, const char* stage)
{
    if (FAILED(result))
    {
        throw std::runtime_error(std::string(stage) + " failed");
    }
}

void writeErrorJson(const std::string& requestId)
{
    std::cout << "{\"ok\":false,\"request_id\":\""
              << trustcircuit::json::escape(requestId)
              << "\",\"result\":null,\"result_hash\":null,"
                 "\"actual_privacy_cost_fixed\":null,"
                 "\"transcript_hash\":null,\"attestation_evidence\":null,"
                 "\"timings_us\":null,\"error\":\"request rejected\"}\n";
}
}

int main(int argc, char* argv[])
{
    std::string requestId;
    try
    {
        if (argc != 2)
        {
            throw std::runtime_error("usage: TrustCircuitNative.exe REQUEST.json");
        }
        const auto hostTotalStarted = std::chrono::steady_clock::now();
        auto request = parseRequest(trustcircuit::json::parseObject(
            loadTextFile(argv[1])));
        requestId = request.requestId;
        SecureBuffer keyCopy(request.key);
        SecureZeroMemory(request.key.data(), request.key.size());
        const auto ciphertext = loadBinaryFile(request.encryptedPayloadPath);
        const auto executionUnixMs = currentUnixMilliseconds();
        const auto processStartupUs = elapsedMicroseconds(processStarted);
        const auto tscTicksPerUs = calibrateTscTicksPerMicrosecond();

        if (keyCopy.bytes.size() != aes256KeyBytes ||
            request.nonce.size() != gcmNonceBytes ||
            request.authenticationTag.size() != gcmTagBytes ||
            request.expectedDataHash.size() != sha256DigestBytes ||
            ciphertext.size() < trustcircuit::processing::datasetHeaderBytes ||
            ciphertext.size() > maxEncryptedPayloadBytes ||
            request.aad.size() > maxAadBytes || request.requestId.empty() ||
            request.assetId.empty() || request.consumerId.empty() ||
            request.requestId.size() > maxIdentifierBytes ||
            request.assetId.size() > maxIdentifierBytes ||
            request.consumerId.size() > maxIdentifierBytes ||
            request.policyHash.size() != 64 || !isLowerHex(request.policyHash) ||
            request.encryptedPayloadPath.size() > maxPayloadPathBytes ||
            executionUnixMs > request.deadlineUnixMs)
        {
            throw std::runtime_error("request bounds validation failed");
        }

        const auto expectedAad = buildCanonicalAad(request);
        if (!constantTimeEqual(request.aad, expectedAad))
        {
            throw std::runtime_error("canonical AAD mismatch");
        }

        BCryptKey symmetricKey;
        const auto keyStatus = BCryptGenerateSymmetricKey(
            BCRYPT_AES_GCM_ALG_HANDLE,
            &symmetricKey.value,
            nullptr,
            0,
            keyCopy.bytes.data(),
            static_cast<ULONG>(keyCopy.bytes.size()),
            0);
        if (keyStatus < 0)
        {
            throw std::runtime_error("AES key setup failed");
        }

        BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO cipherInfo{};
        BCRYPT_INIT_AUTH_MODE_INFO(cipherInfo);
        cipherInfo.pbNonce = request.nonce.data();
        cipherInfo.cbNonce = static_cast<ULONG>(request.nonce.size());
        cipherInfo.pbAuthData = request.aad.data();
        cipherInfo.cbAuthData = static_cast<ULONG>(request.aad.size());
        cipherInfo.pbTag = request.authenticationTag.data();
        cipherInfo.cbTag = static_cast<ULONG>(request.authenticationTag.size());

        const auto decryptStarted = __rdtsc();
        SecureBuffer plaintext(ciphertext.size());
        ULONG plaintextSize = 0;
        const auto decryptStatus = BCryptDecrypt(
            symmetricKey.value,
            const_cast<PUCHAR>(ciphertext.data()),
            static_cast<ULONG>(ciphertext.size()),
            &cipherInfo,
            nullptr,
            0,
            plaintext.bytes.data(),
            static_cast<ULONG>(plaintext.bytes.size()),
            &plaintextSize,
            0);
        const auto decryptUs = (__rdtsc() - decryptStarted) / tscTicksPerUs;
        if (decryptStatus < 0 || plaintextSize != plaintext.bytes.size())
        {
            throw std::runtime_error("AES-GCM authentication failed");
        }

        const auto hashStarted = __rdtsc();
        std::vector<std::uint8_t> actualDataHash;
        check(sha256(plaintext.bytes, actualDataHash), "data hash");
        const auto hashUs = (__rdtsc() - hashStarted) / tscTicksPerUs;
        if (!constantTimeEqual(actualDataHash, request.expectedDataHash))
        {
            throw std::runtime_error("committed data hash mismatch");
        }

        std::int64_t resultFixed = 0;
        std::uint64_t rowCount = 0;
        std::uint64_t aggregateUs = 0;
        check(trustcircuit::processing::aggregateDataset(
            plaintext.bytes,
            request.functionId,
            request.lowerBoundFixed,
            request.upperBoundFixed,
            tscTicksPerUs,
            resultFixed,
            rowCount,
            aggregateUs), "aggregate");

        std::uint64_t actualPrivacyCostFixed = 0;
        const auto dpStarted = __rdtsc();
        if (request.applyDp)
        {
            check(addGaussianNoise(
                request.functionId,
                rowCount,
                request.lowerBoundFixed,
                request.upperBoundFixed,
                request.epsilonRequestedFixed,
                request.deltaRequestedFixed,
                resultFixed,
                actualPrivacyCostFixed), "DP noise");
        }
        const auto dpNoiseUs = (__rdtsc() - dpStarted) / tscTicksPerUs;

        const auto transcriptStarted = __rdtsc();
        std::vector<std::uint8_t> resultCanonical;
        appendBytes(resultCanonical, resultDomain);
        appendInt64LittleEndian(resultCanonical, resultFixed);
        std::vector<std::uint8_t> resultHash;
        check(sha256(resultCanonical, resultHash), "result hash");
        std::vector<std::uint8_t> nativeIdentity;
        check(sha256(nativeIdentityDomain, nativeIdentity), "native identity");
        std::vector<std::uint8_t> transcript;
        appendBytes(transcript, transcriptDomain);
        appendBytes(transcript, expectedAad);
        appendUint64LittleEndian(transcript, executionUnixMs);
        appendInt64LittleEndian(transcript, resultFixed);
        appendUint64LittleEndian(transcript, actualPrivacyCostFixed);
        appendBytes(transcript, resultHash);
        appendBytes(transcript, nativeIdentity);
        std::vector<std::uint8_t> transcriptHash;
        check(sha256(transcript, transcriptHash), "transcript hash");
        const auto transcriptUs = (__rdtsc() - transcriptStarted) / tscTicksPerUs;
        const auto hostTotalUs = elapsedMicroseconds(hostTotalStarted);

        std::cout
            << "{\"ok\":true,\"request_id\":\""
            << trustcircuit::json::escape(request.requestId)
            << "\",\"result\":" << formatFixed(resultFixed)
            << ",\"result_fixed\":" << resultFixed
            << ",\"result_hash\":\"" << encodeHex(resultHash)
            << "\",\"actual_privacy_cost_fixed\":"
            << actualPrivacyCostFixed
            << ",\"transcript_hash\":\"" << encodeHex(transcriptHash)
            << "\",\"enclave_identity\":\"" << encodeHex(nativeIdentity)
            << "\",\"execution_unix_ms\":" << executionUnixMs
            << ",\"native_attestation_evidence\":null,"
               "\"attestation_evidence\":null,\"row_count\":"
            << rowCount << ",\"timings_us\":{\"host_total\":"
            << hostTotalUs << ",\"process_startup\":" << processStartupUs
            << ",\"enclave_call\":0,\"decrypt\":" << decryptUs
            << ",\"hash\":" << hashUs
            << ",\"aggregate\":" << aggregateUs
            << ",\"dp_noise\":" << dpNoiseUs
            << ",\"transcript\":" << transcriptUs
            << ",\"attestation\":0},\"error\":null}\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "TrustCircuitNative failed: " << error.what() << "\n";
        writeErrorJson(requestId);
        return 1;
    }
}
