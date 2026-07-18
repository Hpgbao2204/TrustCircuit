#include "pch.h"

#include <VbsEnclave\Enclave\Implementation\Trusted.h>

#include <bcrypt.h>
#include <cmath>
#include <cstring>
#include <intrin.h>
#include <limits>
#include <span>
#include <string>
#include <wil/stl.h>

namespace
{
constexpr std::size_t maxHashBufferBytes = 1024 * 1024;
constexpr std::size_t sha256DigestBytes = 32;
constexpr std::size_t datasetHeaderBytes = 16;
constexpr std::uint32_t datasetVersion = 1;
constexpr std::uint32_t maxDatasetRows = 100000;
constexpr std::int64_t fixedPointScale = 1000000;
constexpr std::uint32_t functionCount = 1;
constexpr std::uint32_t functionMean = 2;
constexpr std::size_t aes256KeyBytes = 32;
constexpr std::size_t gcmNonceBytes = 12;
constexpr std::size_t gcmTagBytes = 16;
constexpr std::size_t maxIdentifierBytes = 128;
constexpr std::size_t maxPayloadPathBytes = 1024;
constexpr std::size_t maxAadBytes = 4096;
constexpr std::size_t maxEncryptedPayloadBytes =
    datasetHeaderBytes +
    static_cast<std::size_t>(maxDatasetRows) * sizeof(std::int64_t);
constexpr std::uint8_t datasetMagic[8] = {
    'T', 'C', 'V', 'B', 'S', 'D', 'S', '1'};
constexpr std::uint8_t requestDomain[] =
    "TrustCircuit.Request.v1";
constexpr std::uint8_t resultDomain[] =
    "TrustCircuit.Result.v1";
constexpr std::uint8_t transcriptDomain[] =
    "TrustCircuit.Execution.v1";
constexpr std::uint8_t enclaveIdentity[] =
    "TrustCircuitVbsEnclave.Phase5";
constexpr long double epsilonFixedScale = 1000000.0L;
constexpr long double deltaFixedScale = 1000000000000.0L;
constexpr long double twoPi =
    6.283185307179586476925286766559005768L;

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
        volatile std::uint8_t* current = bytes.data();
        for (std::size_t index = 0; index < bytes.size(); ++index)
        {
            current[index] = 0;
        }
    }
    SecureBuffer(const SecureBuffer&) = delete;
    SecureBuffer& operator=(const SecureBuffer&) = delete;
    std::vector<std::uint8_t> bytes;
};

std::uint32_t readUint32LittleEndian(
    std::span<const std::uint8_t> input,
    std::size_t offset)
{
    return static_cast<std::uint32_t>(input[offset]) |
        (static_cast<std::uint32_t>(input[offset + 1]) << 8) |
        (static_cast<std::uint32_t>(input[offset + 2]) << 16) |
        (static_cast<std::uint32_t>(input[offset + 3]) << 24);
}

std::int64_t readInt64LittleEndian(
    std::span<const std::uint8_t> input,
    std::size_t offset)
{
    std::uint64_t value = 0;
    for (std::size_t index = 0; index < sizeof(value); ++index)
    {
        value |= static_cast<std::uint64_t>(input[offset + index]) <<
            (index * 8);
    }
    return static_cast<std::int64_t>(value);
}

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
    for (const auto character : value)
    {
        if (!((character >= '0' && character <= '9') ||
              (character >= 'a' && character <= 'f')))
        {
            return false;
        }
    }
    return true;
}

HRESULT sha256(
    std::span<const std::uint8_t> input,
    std::vector<std::uint8_t>& digest)
{
    wil::unique_bcrypt_hash hash;
    NTSTATUS status = BCryptCreateHash(
        BCRYPT_SHA256_ALG_HANDLE,
        &hash,
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
            hash.get(),
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
        hash.get(),
        digest.data(),
        static_cast<ULONG>(digest.size()),
        0);
    if (status < 0)
    {
        digest.clear();
        return HRESULT_FROM_NT(status);
    }
    return S_OK;
}

std::vector<std::uint8_t> buildCanonicalAad(
    const std::string& requestId,
    const std::string& assetId,
    const std::string& consumerId,
    const std::string& policyHash,
    const std::string& encryptedPayloadPath,
    std::span<const std::uint8_t> expectedDataHash,
    std::uint64_t policyVersion,
    std::uint32_t functionId,
    std::uint64_t epsilonRequestedFixed,
    std::uint64_t deltaRequestedFixed,
    std::int64_t lowerBoundFixed,
    std::int64_t upperBoundFixed,
    std::uint64_t deadlineUnixMs,
    bool applyDp)
{
    std::vector<std::uint8_t> canonical;
    canonical.reserve(512 + encryptedPayloadPath.size());
    appendBytes(canonical, requestDomain);
    appendSizedString(canonical, requestId);
    appendSizedString(canonical, assetId);
    appendSizedString(canonical, consumerId);
    appendSizedString(canonical, policyHash);
    appendSizedString(canonical, encryptedPayloadPath);
    appendBytes(canonical, expectedDataHash);
    appendUint64LittleEndian(canonical, policyVersion);
    appendUint32LittleEndian(canonical, functionId);
    appendUint64LittleEndian(canonical, epsilonRequestedFixed);
    appendUint64LittleEndian(canonical, deltaRequestedFixed);
    appendInt64LittleEndian(canonical, lowerBoundFixed);
    appendInt64LittleEndian(canonical, upperBoundFixed);
    appendUint64LittleEndian(canonical, deadlineUnixMs);
    canonical.push_back(applyDp ? 1 : 0);
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
        noisyResult <
            static_cast<long double>((std::numeric_limits<std::int64_t>::min)()) ||
        noisyResult >
            static_cast<long double>((std::numeric_limits<std::int64_t>::max)()))
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
        if (converted < minimumRdpEpsilon)
        {
            minimumRdpEpsilon = converted;
        }
    }
    const auto conservativeEpsilon =
        minimumRdpEpsilon > epsilon ? minimumRdpEpsilon : epsilon;
    const auto conservativeFixed =
        std::ceil(conservativeEpsilon * epsilonFixedScale);
    if (!std::isfinite(conservativeFixed) || conservativeFixed < 0 ||
        conservativeFixed > static_cast<long double>(
            (std::numeric_limits<std::uint64_t>::max)()))
    {
        return HRESULT_FROM_WIN32(ERROR_ARITHMETIC_OVERFLOW);
    }
    actualPrivacyCostFixed =
        static_cast<std::uint64_t>(conservativeFixed);
    return S_OK;
}
}

std::uint32_t VbsEnclave::Trusted::Implementation::DoSecretMath(
    _In_ std::uint32_t val1,
    _In_ std::uint32_t val2)
{
    return val1 * val2;
}

HRESULT VbsEnclave::Trusted::Implementation::HashBuffer(
    _In_ const std::vector<std::uint8_t>& input,
    _Out_ std::vector<std::uint8_t>& digest)
{
    if (input.size() > maxHashBufferBytes)
    {
        return E_INVALIDARG;
    }

    return sha256(input, digest);
}

HRESULT VbsEnclave::Trusted::Implementation::AggregateDataset(
    _In_ const std::vector<std::uint8_t>& payload,
    _In_ std::uint32_t functionId,
    _In_ std::int64_t lowerBoundFixed,
    _In_ std::int64_t upperBoundFixed,
    _In_ std::uint64_t tscTicksPerUs,
    _Out_ std::int64_t& resultFixed,
    _Out_ std::uint64_t& rowCount,
    _Out_ std::uint64_t& aggregateUs)
{
    const auto started = __rdtsc();
    resultFixed = 0;
    rowCount = 0;
    aggregateUs = 0;

    if (tscTicksPerUs == 0 ||
        (functionId != functionCount && functionId != functionMean))
    {
        return E_INVALIDARG;
    }
    if (lowerBoundFixed > upperBoundFixed ||
        payload.size() < datasetHeaderBytes ||
        !std::equal(
            std::begin(datasetMagic),
            std::end(datasetMagic),
            payload.begin()))
    {
        return E_INVALIDARG;
    }

    const auto version = readUint32LittleEndian(payload, 8);
    const auto rows = readUint32LittleEndian(payload, 12);
    if (version != datasetVersion || rows > maxDatasetRows)
    {
        return E_INVALIDARG;
    }
    if (rows >
        ((std::numeric_limits<std::size_t>::max)() - datasetHeaderBytes) /
            sizeof(std::int64_t))
    {
        return E_INVALIDARG;
    }
    const auto expectedSize = datasetHeaderBytes +
        static_cast<std::size_t>(rows) * sizeof(std::int64_t);
    if (payload.size() != expectedSize ||
        (functionId == functionMean && rows == 0))
    {
        return E_INVALIDARG;
    }

    std::int64_t sum = 0;
    for (std::uint32_t index = 0; index < rows; ++index)
    {
        const auto value = readInt64LittleEndian(
            payload,
            datasetHeaderBytes +
                static_cast<std::size_t>(index) * sizeof(std::int64_t));
        if (value < lowerBoundFixed || value > upperBoundFixed)
        {
            return E_INVALIDARG;
        }
        if ((value > 0 &&
             sum > (std::numeric_limits<std::int64_t>::max)() - value) ||
            (value < 0 &&
             sum < (std::numeric_limits<std::int64_t>::min)() - value))
        {
            return HRESULT_FROM_WIN32(ERROR_ARITHMETIC_OVERFLOW);
        }
        sum += value;
    }

    if (functionId == functionCount)
    {
        if (static_cast<std::uint64_t>(rows) >
            static_cast<std::uint64_t>(
                (std::numeric_limits<std::int64_t>::max)() /
                fixedPointScale))
        {
            return HRESULT_FROM_WIN32(ERROR_ARITHMETIC_OVERFLOW);
        }
        resultFixed = static_cast<std::int64_t>(rows) * fixedPointScale;
    }
    else
    {
        resultFixed = sum / static_cast<std::int64_t>(rows);
    }

    rowCount = rows;
    aggregateUs = (__rdtsc() - started) / tscTicksPerUs;
    return S_OK;
}

HRESULT VbsEnclave::Trusted::Implementation::ExecuteEncrypted(
    _In_ const std::vector<std::uint8_t>& ciphertext,
    _In_ const std::vector<std::uint8_t>& key,
    _In_ const std::vector<std::uint8_t>& nonce,
    _In_ const std::vector<std::uint8_t>& authenticationTag,
    _In_ const std::vector<std::uint8_t>& aad,
    _In_ const std::vector<std::uint8_t>& expectedDataHash,
    _In_ const std::string& requestId,
    _In_ const std::string& assetId,
    _In_ const std::string& consumerId,
    _In_ const std::string& policyHash,
    _In_ const std::string& encryptedPayloadPath,
    _In_ std::uint64_t policyVersion,
    _In_ std::uint32_t functionId,
    _In_ std::uint64_t epsilonRequestedFixed,
    _In_ std::uint64_t deltaRequestedFixed,
    _In_ std::int64_t lowerBoundFixed,
    _In_ std::int64_t upperBoundFixed,
    _In_ std::uint64_t deadlineUnixMs,
    _In_ std::uint64_t executionUnixMs,
    _In_ bool applyDp,
    _In_ std::uint64_t tscTicksPerUs,
    _Out_ std::int64_t& resultFixed,
    _Out_ std::uint64_t& rowCount,
    _Out_ std::uint64_t& actualPrivacyCostFixed,
    _Out_ std::vector<std::uint8_t>& resultHash,
    _Out_ std::vector<std::uint8_t>& transcriptHash,
    _Out_ std::uint64_t& decryptUs,
    _Out_ std::uint64_t& hashUs,
    _Out_ std::uint64_t& aggregateUs,
    _Out_ std::uint64_t& dpNoiseUs,
    _Out_ std::uint64_t& transcriptUs)
{
    resultFixed = 0;
    rowCount = 0;
    actualPrivacyCostFixed = 0;
    resultHash.clear();
    transcriptHash.clear();
    decryptUs = 0;
    hashUs = 0;
    aggregateUs = 0;
    dpNoiseUs = 0;
    transcriptUs = 0;

    if (tscTicksPerUs == 0 || key.size() != aes256KeyBytes ||
        nonce.size() != gcmNonceBytes ||
        authenticationTag.size() != gcmTagBytes ||
        expectedDataHash.size() != sha256DigestBytes ||
        ciphertext.size() < datasetHeaderBytes ||
        ciphertext.size() > maxEncryptedPayloadBytes ||
        aad.size() > maxAadBytes || requestId.empty() || assetId.empty() ||
        consumerId.empty() || requestId.size() > maxIdentifierBytes ||
        assetId.size() > maxIdentifierBytes ||
        consumerId.size() > maxIdentifierBytes || policyHash.size() != 64 ||
        !isLowerHex(policyHash) ||
        encryptedPayloadPath.size() > maxPayloadPathBytes ||
        executionUnixMs > deadlineUnixMs)
    {
        return E_INVALIDARG;
    }
    if ((!applyDp &&
         (epsilonRequestedFixed != 0 || deltaRequestedFixed != 0)) ||
        (applyDp &&
         (epsilonRequestedFixed == 0 ||
          epsilonRequestedFixed >
              static_cast<std::uint64_t>(epsilonFixedScale) ||
          deltaRequestedFixed == 0 ||
          deltaRequestedFixed >=
              static_cast<std::uint64_t>(deltaFixedScale))))
    {
        return E_INVALIDARG;
    }

    const auto expectedAad = buildCanonicalAad(
        requestId,
        assetId,
        consumerId,
        policyHash,
        encryptedPayloadPath,
        expectedDataHash,
        policyVersion,
        functionId,
        epsilonRequestedFixed,
        deltaRequestedFixed,
        lowerBoundFixed,
        upperBoundFixed,
        deadlineUnixMs,
        applyDp);
    if (!constantTimeEqual(aad, expectedAad))
    {
        return E_INVALIDARG;
    }

    SecureBuffer keyCopy(key);
    wil::unique_bcrypt_key symmetricKey;
    NTSTATUS status = BCryptGenerateSymmetricKey(
        BCRYPT_AES_GCM_ALG_HANDLE,
        &symmetricKey,
        nullptr,
        0,
        keyCopy.bytes.data(),
        static_cast<ULONG>(keyCopy.bytes.size()),
        0);
    if (status < 0)
    {
        return HRESULT_FROM_NT(status);
    }

    BCRYPT_AUTHENTICATED_CIPHER_MODE_INFO cipherInfo{};
    BCRYPT_INIT_AUTH_MODE_INFO(cipherInfo);
    cipherInfo.pbNonce = const_cast<PUCHAR>(nonce.data());
    cipherInfo.cbNonce = static_cast<ULONG>(nonce.size());
    cipherInfo.pbAuthData = const_cast<PUCHAR>(aad.data());
    cipherInfo.cbAuthData = static_cast<ULONG>(aad.size());
    cipherInfo.pbTag = const_cast<PUCHAR>(authenticationTag.data());
    cipherInfo.cbTag = static_cast<ULONG>(authenticationTag.size());

    const auto decryptStarted = __rdtsc();
    SecureBuffer plaintext(ciphertext.size());
    ULONG plaintextSize = 0;
    status = BCryptDecrypt(
        symmetricKey.get(),
        const_cast<PUCHAR>(ciphertext.data()),
        static_cast<ULONG>(ciphertext.size()),
        &cipherInfo,
        nullptr,
        0,
        plaintext.bytes.data(),
        static_cast<ULONG>(plaintext.bytes.size()),
        &plaintextSize,
        0);
    decryptUs = (__rdtsc() - decryptStarted) / tscTicksPerUs;
    if (status < 0 || plaintextSize != plaintext.bytes.size())
    {
        return status < 0 ? HRESULT_FROM_NT(status) : E_FAIL;
    }

    const auto hashStarted = __rdtsc();
    std::vector<std::uint8_t> actualDataHash;
    RETURN_IF_FAILED(sha256(plaintext.bytes, actualDataHash));
    hashUs = (__rdtsc() - hashStarted) / tscTicksPerUs;
    if (!constantTimeEqual(actualDataHash, expectedDataHash))
    {
        return HRESULT_FROM_WIN32(ERROR_DATA_CHECKSUM_ERROR);
    }

    RETURN_IF_FAILED(AggregateDataset(
        plaintext.bytes,
        functionId,
        lowerBoundFixed,
        upperBoundFixed,
        tscTicksPerUs,
        resultFixed,
        rowCount,
        aggregateUs));

    const auto dpStarted = __rdtsc();
    if (applyDp)
    {
        RETURN_IF_FAILED(addGaussianNoise(
            functionId,
            rowCount,
            lowerBoundFixed,
            upperBoundFixed,
            epsilonRequestedFixed,
            deltaRequestedFixed,
            resultFixed,
            actualPrivacyCostFixed));
    }
    dpNoiseUs = (__rdtsc() - dpStarted) / tscTicksPerUs;

    const auto transcriptStarted = __rdtsc();
    std::vector<std::uint8_t> resultCanonical;
    appendBytes(resultCanonical, resultDomain);
    appendInt64LittleEndian(resultCanonical, resultFixed);
    RETURN_IF_FAILED(sha256(resultCanonical, resultHash));

    std::vector<std::uint8_t> transcript;
    appendBytes(transcript, transcriptDomain);
    appendBytes(transcript, expectedAad);
    appendUint64LittleEndian(transcript, executionUnixMs);
    appendInt64LittleEndian(transcript, resultFixed);
    appendUint64LittleEndian(transcript, actualPrivacyCostFixed);
    appendBytes(transcript, resultHash);
    appendBytes(transcript, enclaveIdentity);
    RETURN_IF_FAILED(sha256(transcript, transcriptHash));
    transcriptUs = (__rdtsc() - transcriptStarted) / tscTicksPerUs;
    return S_OK;
}
