#include "pch.h"

#include "..\Shared\DatasetAggregate.h"

#include <VbsEnclave\Enclave\Implementation\Trusted.h>

#include <algorithm>
#include <array>
#include <bcrypt.h>
#include <cmath>
#include <cstring>
#include <intrin.h>
#include <limits>
#include <ntenclv.h>
#include <span>
#include <string>
#include <winenclaveapi.h>
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
constexpr std::size_t maxAttestationEvidenceBytes = 64 * 1024;
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
constexpr std::uint8_t enclaveIdentityDomain[] =
    "TrustCircuit.EnclaveIdentity.v1";
constexpr std::uint8_t attestationBindingDomain[] =
    "TrustCircuit.Attestation.v1";
constexpr std::uint64_t maxAttestationLifetimeMs = 5 * 60 * 1000;
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

HRESULT hashEnclaveIdentity(
    const ENCLAVE_IDENTITY& identity,
    std::vector<std::uint8_t>& digest)
{
    std::vector<std::uint8_t> canonical;
    canonical.reserve(192);
    appendBytes(canonical, enclaveIdentityDomain);
    appendBytes(canonical, identity.OwnerId);
    appendBytes(canonical, identity.UniqueId);
    appendBytes(canonical, identity.AuthorId);
    appendBytes(canonical, identity.FamilyId);
    appendBytes(canonical, identity.ImageId);
    appendUint32LittleEndian(canonical, identity.EnclaveSvn);
    appendUint32LittleEndian(canonical, identity.SecureKernelSvn);
    appendUint32LittleEndian(canonical, identity.PlatformSvn);
    appendUint32LittleEndian(canonical, identity.Flags);
    appendUint32LittleEndian(canonical, identity.SigningLevel);
    appendUint32LittleEndian(canonical, identity.EnclaveType);
    return sha256(canonical, digest);
}

HRESULT currentEnclaveIdentityHash(
    std::vector<std::uint8_t>& digest)
{
    ENCLAVE_INFORMATION information{};
    RETURN_IF_FAILED(EnclaveGetEnclaveInformation(
        sizeof(information),
        &information));
    if (information.EnclaveType != ENCLAVE_TYPE_VBS ||
        information.Identity.EnclaveType != ENCLAVE_TYPE_VBS)
    {
        return E_UNEXPECTED;
    }
    return hashEnclaveIdentity(information.Identity, digest);
}

HRESULT buildTranscriptHash(
    std::span<const std::uint8_t> canonicalAad,
    std::uint64_t executionUnixMs,
    std::int64_t resultFixed,
    std::uint64_t actualPrivacyCostFixed,
    std::span<const std::uint8_t> resultHash,
    std::span<const std::uint8_t> enclaveIdentityHash,
    std::vector<std::uint8_t>& transcriptHash)
{
    if (resultHash.size() != sha256DigestBytes ||
        enclaveIdentityHash.size() != sha256DigestBytes)
    {
        return E_INVALIDARG;
    }

    std::vector<std::uint8_t> transcript;
    transcript.reserve(
        sizeof(transcriptDomain) + canonicalAad.size() + 96);
    appendBytes(transcript, transcriptDomain);
    appendBytes(transcript, canonicalAad);
    appendUint64LittleEndian(transcript, executionUnixMs);
    appendInt64LittleEndian(transcript, resultFixed);
    appendUint64LittleEndian(transcript, actualPrivacyCostFixed);
    appendBytes(transcript, resultHash);
    appendBytes(transcript, enclaveIdentityHash);
    return sha256(transcript, transcriptHash);
}

HRESULT buildAttestationBinding(
    std::span<const std::uint8_t> transcriptHash,
    std::array<std::uint8_t, ENCLAVE_REPORT_DATA_LENGTH>& binding)
{
    if (transcriptHash.size() != sha256DigestBytes)
    {
        return E_INVALIDARG;
    }

    std::copy(transcriptHash.begin(), transcriptHash.end(), binding.begin());
    std::vector<std::uint8_t> domainSeparated;
    domainSeparated.reserve(
        sizeof(attestationBindingDomain) + transcriptHash.size());
    appendBytes(domainSeparated, attestationBindingDomain);
    appendBytes(domainSeparated, transcriptHash);
    std::vector<std::uint8_t> secondHalf;
    RETURN_IF_FAILED(sha256(domainSeparated, secondHalf));
    std::copy(
        secondHalf.begin(),
        secondHalf.end(),
        binding.begin() + sha256DigestBytes);
    return S_OK;
}

HRESULT generateAttestationEvidence(
    std::span<const std::uint8_t> transcriptHash,
    std::vector<std::uint8_t>& evidence)
{
    std::array<std::uint8_t, ENCLAVE_REPORT_DATA_LENGTH> binding{};
    RETURN_IF_FAILED(buildAttestationBinding(transcriptHash, binding));

    std::uint32_t requiredSize = 0;
    RETURN_IF_FAILED(EnclaveGetAttestationReport(
        binding.data(),
        nullptr,
        0,
        &requiredSize));
    if (requiredSize <
            sizeof(VBS_ENCLAVE_REPORT_PKG_HEADER) +
                sizeof(VBS_ENCLAVE_REPORT) ||
        requiredSize > maxAttestationEvidenceBytes)
    {
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    }

    evidence.assign(requiredSize, 0);
    std::uint32_t actualSize = 0;
    const auto result = EnclaveGetAttestationReport(
        binding.data(),
        evidence.data(),
        static_cast<std::uint32_t>(evidence.size()),
        &actualSize);
    if (FAILED(result))
    {
        evidence.clear();
        return result;
    }
    if (actualSize != requiredSize)
    {
        evidence.clear();
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    }
    return S_OK;
}

HRESULT parseVbsAttestationEvidence(
    std::span<const std::uint8_t> evidence,
    VBS_ENCLAVE_REPORT& report)
{
    if (evidence.size() <
            sizeof(VBS_ENCLAVE_REPORT_PKG_HEADER) +
                sizeof(VBS_ENCLAVE_REPORT) ||
        evidence.size() > maxAttestationEvidenceBytes)
    {
        return E_INVALIDARG;
    }

    VBS_ENCLAVE_REPORT_PKG_HEADER package{};
    std::memcpy(&package, evidence.data(), sizeof(package));
    const auto totalSize =
        static_cast<std::uint64_t>(sizeof(package)) +
        static_cast<std::uint64_t>(package.SignedStatementSize) +
        static_cast<std::uint64_t>(package.SignatureSize);
    if (package.PackageSize != evidence.size() ||
        totalSize != evidence.size() ||
        package.Version != VBS_ENCLAVE_REPORT_PKG_HEADER_VERSION_CURRENT ||
        package.SignatureScheme !=
            VBS_ENCLAVE_REPORT_SIGNATURE_SCHEME_SHA256_RSA_PSS_SHA256 ||
        package.SignedStatementSize < sizeof(VBS_ENCLAVE_REPORT) ||
        package.SignatureSize == 0 || package.Reserved != 0)
    {
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
    }

    std::memcpy(
        &report,
        evidence.data() + sizeof(package),
        sizeof(report));
    if (report.ReportSize != package.SignedStatementSize ||
        report.ReportVersion != VBS_ENCLAVE_REPORT_VERSION_CURRENT ||
        report.EnclaveIdentity.EnclaveType != ENCLAVE_TYPE_VBS)
    {
        return HRESULT_FROM_WIN32(ERROR_INVALID_DATA);
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
    return trustcircuit::processing::aggregateDataset(
        payload,
        functionId,
        lowerBoundFixed,
        upperBoundFixed,
        tscTicksPerUs,
        resultFixed,
        rowCount,
        aggregateUs);
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
    _Out_ std::vector<std::uint8_t>& enclaveIdentityHash,
    _Out_ std::vector<std::uint8_t>& attestationEvidence,
    _Out_ std::uint64_t& decryptUs,
    _Out_ std::uint64_t& hashUs,
    _Out_ std::uint64_t& aggregateUs,
    _Out_ std::uint64_t& dpNoiseUs,
    _Out_ std::uint64_t& transcriptUs,
    _Out_ std::uint64_t& attestationUs)
{
    resultFixed = 0;
    rowCount = 0;
    actualPrivacyCostFixed = 0;
    resultHash.clear();
    transcriptHash.clear();
    enclaveIdentityHash.clear();
    attestationEvidence.clear();
    decryptUs = 0;
    hashUs = 0;
    aggregateUs = 0;
    dpNoiseUs = 0;
    transcriptUs = 0;
    attestationUs = 0;

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

    RETURN_IF_FAILED(currentEnclaveIdentityHash(enclaveIdentityHash));
    RETURN_IF_FAILED(buildTranscriptHash(
        expectedAad,
        executionUnixMs,
        resultFixed,
        actualPrivacyCostFixed,
        resultHash,
        enclaveIdentityHash,
        transcriptHash));
    transcriptUs = (__rdtsc() - transcriptStarted) / tscTicksPerUs;

    const auto attestationStarted = __rdtsc();
    RETURN_IF_FAILED(generateAttestationEvidence(
        transcriptHash,
        attestationEvidence));
    attestationUs = (__rdtsc() - attestationStarted) / tscTicksPerUs;
    return S_OK;
}

HRESULT VbsEnclave::Trusted::Implementation::ValidateAttestationEvidence(
    _In_ const std::vector<std::uint8_t>& attestationEvidence,
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
    _In_ std::int64_t resultFixed,
    _In_ std::uint64_t actualPrivacyCostFixed,
    _In_ const std::vector<std::uint8_t>& resultHash,
    _In_ const std::vector<std::uint8_t>& expectedTranscriptHash,
    _In_ const std::vector<std::uint8_t>& expectedEnclaveIdentity,
    _In_ std::uint64_t validationUnixMs,
    _In_ std::uint64_t tscTicksPerUs,
    _Out_ std::vector<std::uint8_t>& validatedTranscriptHash,
    _Out_ std::vector<std::uint8_t>& validatedEnclaveIdentity,
    _Out_ std::vector<std::uint8_t>& evidenceHash,
    _Out_ std::uint64_t& issuedAtUnixMs,
    _Out_ std::uint64_t& expiresAtUnixMs,
    _Out_ std::uint64_t& validationUs)
{
    const auto started = __rdtsc();
    validatedTranscriptHash.clear();
    validatedEnclaveIdentity.clear();
    evidenceHash.clear();
    issuedAtUnixMs = 0;
    expiresAtUnixMs = 0;
    validationUs = 0;

    if (tscTicksPerUs == 0 ||
        attestationEvidence.empty() ||
        attestationEvidence.size() > maxAttestationEvidenceBytes ||
        aad.size() > maxAadBytes ||
        expectedDataHash.size() != sha256DigestBytes ||
        resultHash.size() != sha256DigestBytes ||
        expectedTranscriptHash.size() != sha256DigestBytes ||
        expectedEnclaveIdentity.size() != sha256DigestBytes ||
        requestId.empty() || assetId.empty() || consumerId.empty() ||
        requestId.size() > maxIdentifierBytes ||
        assetId.size() > maxIdentifierBytes ||
        consumerId.size() > maxIdentifierBytes ||
        policyHash.size() != 64 || !isLowerHex(policyHash) ||
        encryptedPayloadPath.size() > maxPayloadPathBytes ||
        lowerBoundFixed > upperBoundFixed ||
        (functionId != functionCount && functionId != functionMean) ||
        executionUnixMs > deadlineUnixMs)
    {
        return E_INVALIDARG;
    }
    if ((!applyDp &&
         (epsilonRequestedFixed != 0 || deltaRequestedFixed != 0 ||
          actualPrivacyCostFixed != 0)) ||
        (applyDp &&
         (epsilonRequestedFixed == 0 ||
          epsilonRequestedFixed >
              static_cast<std::uint64_t>(epsilonFixedScale) ||
          deltaRequestedFixed == 0 ||
          deltaRequestedFixed >=
              static_cast<std::uint64_t>(deltaFixedScale) ||
          actualPrivacyCostFixed < epsilonRequestedFixed)))
    {
        return E_INVALIDARG;
    }

    const auto lifetimeExpiry =
        executionUnixMs >
                (std::numeric_limits<std::uint64_t>::max)() -
                    maxAttestationLifetimeMs
            ? (std::numeric_limits<std::uint64_t>::max)()
            : executionUnixMs + maxAttestationLifetimeMs;
    const auto expiry = (std::min)(deadlineUnixMs, lifetimeExpiry);
    if (validationUnixMs < executionUnixMs || validationUnixMs > expiry)
    {
        return HRESULT_FROM_WIN32(ERROR_TIMEOUT);
    }

    const auto canonicalAad = buildCanonicalAad(
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
    if (!constantTimeEqual(aad, canonicalAad))
    {
        return E_INVALIDARG;
    }

    std::vector<std::uint8_t> calculatedResultHash;
    std::vector<std::uint8_t> resultCanonical;
    appendBytes(resultCanonical, resultDomain);
    appendInt64LittleEndian(resultCanonical, resultFixed);
    RETURN_IF_FAILED(sha256(resultCanonical, calculatedResultHash));
    if (!constantTimeEqual(resultHash, calculatedResultHash))
    {
        return HRESULT_FROM_WIN32(ERROR_DATA_CHECKSUM_ERROR);
    }

    VBS_ENCLAVE_REPORT report{};
    RETURN_IF_FAILED(parseVbsAttestationEvidence(
        attestationEvidence,
        report));
    RETURN_IF_FAILED(EnclaveVerifyAttestationReport(
        ENCLAVE_TYPE_VBS,
        attestationEvidence.data(),
        static_cast<std::uint32_t>(attestationEvidence.size())));

    std::vector<std::uint8_t> reportIdentityHash;
    RETURN_IF_FAILED(hashEnclaveIdentity(
        report.EnclaveIdentity,
        reportIdentityHash));
    std::vector<std::uint8_t> validatorEnclaveIdentityHash;
    RETURN_IF_FAILED(currentEnclaveIdentityHash(
        validatorEnclaveIdentityHash));
    if (!constantTimeEqual(reportIdentityHash, expectedEnclaveIdentity) ||
        !constantTimeEqual(
            reportIdentityHash,
            validatorEnclaveIdentityHash))
    {
        return HRESULT_FROM_WIN32(ERROR_ACCESS_DENIED);
    }

    std::vector<std::uint8_t> calculatedTranscriptHash;
    RETURN_IF_FAILED(buildTranscriptHash(
        canonicalAad,
        executionUnixMs,
        resultFixed,
        actualPrivacyCostFixed,
        calculatedResultHash,
        reportIdentityHash,
        calculatedTranscriptHash));
    if (!constantTimeEqual(
            calculatedTranscriptHash,
            expectedTranscriptHash))
    {
        return HRESULT_FROM_WIN32(ERROR_DATA_CHECKSUM_ERROR);
    }

    std::array<std::uint8_t, ENCLAVE_REPORT_DATA_LENGTH> expectedBinding{};
    RETURN_IF_FAILED(buildAttestationBinding(
        calculatedTranscriptHash,
        expectedBinding));
    if (!constantTimeEqual(report.EnclaveData, expectedBinding))
    {
        return HRESULT_FROM_WIN32(ERROR_DATA_CHECKSUM_ERROR);
    }

    RETURN_IF_FAILED(sha256(attestationEvidence, evidenceHash));
    validatedTranscriptHash = std::move(calculatedTranscriptHash);
    validatedEnclaveIdentity = std::move(reportIdentityHash);
    issuedAtUnixMs = executionUnixMs;
    expiresAtUnixMs = expiry;
    validationUs = (__rdtsc() - started) / tscTicksPerUs;
    return S_OK;
}
