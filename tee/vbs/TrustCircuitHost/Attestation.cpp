#include "Attestation.h"

#include <Windows.h>
#include <bcrypt.h>
#include <ncrypt.h>
#include <wincrypt.h>

#include <array>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifndef TRUSTCIRCUIT_VALIDATOR_CERT_THUMBPRINT
#error TRUSTCIRCUIT_VALIDATOR_CERT_THUMBPRINT must be configured
#endif

#define TRUSTCIRCUIT_STRINGIFY_INNER(value) #value
#define TRUSTCIRCUIT_STRINGIFY(value) TRUSTCIRCUIT_STRINGIFY_INNER(value)

namespace trustcircuit::attestation
{
namespace
{
constexpr std::size_t sha256Bytes = 32;
constexpr std::size_t sha1Bytes = 20;
constexpr std::uint8_t statementDomain[] =
    "TrustCircuit.AttestationStatement.v1";
constexpr char signingThumbprint[] =
    TRUSTCIRCUIT_STRINGIFY(TRUSTCIRCUIT_VALIDATOR_CERT_THUMBPRINT);

class CertificateStore
{
public:
    CertificateStore()
        : handle(CertOpenStore(
              CERT_STORE_PROV_SYSTEM_W,
              0,
              0,
              CERT_SYSTEM_STORE_CURRENT_USER | CERT_STORE_OPEN_EXISTING_FLAG |
                  CERT_STORE_READONLY_FLAG,
              L"MY"))
    {
        if (handle == nullptr)
        {
            throw std::runtime_error("cannot open validator certificate store");
        }
    }

    ~CertificateStore()
    {
        CertCloseStore(handle, 0);
    }

    CertificateStore(const CertificateStore&) = delete;
    CertificateStore& operator=(const CertificateStore&) = delete;
    HCERTSTORE handle{};
};

class CertificateContext
{
public:
    explicit CertificateContext(PCCERT_CONTEXT value) : handle(value)
    {
        if (handle == nullptr)
        {
            throw std::runtime_error(
                "configured validator certificate was not found");
        }
    }

    ~CertificateContext()
    {
        CertFreeCertificateContext(handle);
    }

    CertificateContext(const CertificateContext&) = delete;
    CertificateContext& operator=(const CertificateContext&) = delete;
    CertificateContext(CertificateContext&& other) noexcept
        : handle(std::exchange(other.handle, nullptr))
    {
    }
    PCCERT_CONTEXT handle{};
};

std::uint8_t decodeHexNibble(char value)
{
    if (value >= '0' && value <= '9')
    {
        return static_cast<std::uint8_t>(value - '0');
    }
    if (value >= 'a' && value <= 'f')
    {
        return static_cast<std::uint8_t>(value - 'a' + 10);
    }
    if (value >= 'A' && value <= 'F')
    {
        return static_cast<std::uint8_t>(value - 'A' + 10);
    }
    throw std::runtime_error("invalid validator certificate thumbprint");
}

std::array<std::uint8_t, sha1Bytes> decodeThumbprint()
{
    constexpr auto length = sizeof(signingThumbprint) - 1;
    static_assert(length == sha1Bytes * 2);
    std::array<std::uint8_t, sha1Bytes> decoded{};
    for (std::size_t index = 0; index < decoded.size(); ++index)
    {
        decoded[index] = static_cast<std::uint8_t>(
            (decodeHexNibble(signingThumbprint[index * 2]) << 4) |
            decodeHexNibble(signingThumbprint[index * 2 + 1]));
    }
    return decoded;
}

CertificateContext findSigningCertificate(CertificateStore& store)
{
    auto thumbprint = decodeThumbprint();
    CRYPT_HASH_BLOB hash{
        static_cast<DWORD>(thumbprint.size()), thumbprint.data()};
    auto* certificate = CertFindCertificateInStore(
        store.handle,
        X509_ASN_ENCODING | PKCS_7_ASN_ENCODING,
        0,
        CERT_FIND_SHA1_HASH,
        &hash,
        nullptr);
    CertificateContext context(certificate);
    if (CertVerifyTimeValidity(nullptr, context.handle->pCertInfo) != 0)
    {
        throw std::runtime_error("validator certificate is not time-valid");
    }
    return context;
}

std::vector<std::uint8_t> sha256(
    std::span<const std::uint8_t> input)
{
    BCRYPT_HASH_HANDLE hash = nullptr;
    auto status = BCryptCreateHash(
        BCRYPT_SHA256_ALG_HANDLE,
        &hash,
        nullptr,
        0,
        nullptr,
        0,
        0);
    if (status < 0)
    {
        throw std::runtime_error("cannot create validator SHA-256 hash");
    }
    try
    {
        if (!input.empty())
        {
            status = BCryptHashData(
                hash,
                const_cast<PUCHAR>(input.data()),
                static_cast<ULONG>(input.size()),
                0);
            if (status < 0)
            {
                throw std::runtime_error("cannot update validator SHA-256 hash");
            }
        }
        std::vector<std::uint8_t> digest(sha256Bytes);
        status = BCryptFinishHash(
            hash,
            digest.data(),
            static_cast<ULONG>(digest.size()),
            0);
        if (status < 0)
        {
            throw std::runtime_error("cannot finish validator SHA-256 hash");
        }
        BCryptDestroyHash(hash);
        return digest;
    }
    catch (...)
    {
        BCryptDestroyHash(hash);
        throw;
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

std::vector<std::uint8_t> canonicalStatement(
    std::span<const std::uint8_t> transcriptHash,
    std::span<const std::uint8_t> enclaveIdentity,
    std::uint64_t issuedAtUnixMs,
    std::uint64_t expiresAtUnixMs,
    std::span<const std::uint8_t> evidenceHash,
    std::span<const std::uint8_t> validatorIdentity)
{
    if (transcriptHash.size() != sha256Bytes ||
        enclaveIdentity.size() != sha256Bytes ||
        evidenceHash.size() != sha256Bytes ||
        validatorIdentity.size() != sha256Bytes ||
        issuedAtUnixMs > expiresAtUnixMs)
    {
        throw std::runtime_error("invalid compact attestation statement");
    }

    std::vector<std::uint8_t> canonical;
    canonical.reserve(sizeof(statementDomain) + 128 + 16);
    canonical.insert(
        canonical.end(), std::begin(statementDomain), std::end(statementDomain));
    canonical.insert(
        canonical.end(), transcriptHash.begin(), transcriptHash.end());
    canonical.insert(
        canonical.end(), enclaveIdentity.begin(), enclaveIdentity.end());
    appendUint64LittleEndian(canonical, issuedAtUnixMs);
    appendUint64LittleEndian(canonical, expiresAtUnixMs);
    canonical.insert(
        canonical.end(), evidenceHash.begin(), evidenceHash.end());
    canonical.insert(
        canonical.end(), validatorIdentity.begin(), validatorIdentity.end());
    return canonical;
}

std::vector<std::uint8_t> certificateIdentity(
    PCCERT_CONTEXT certificate)
{
    return sha256(std::span<const std::uint8_t>(
        certificate->pbCertEncoded,
        certificate->cbCertEncoded));
}
}

Signature signStatement(
    std::span<const std::uint8_t> transcriptHash,
    std::span<const std::uint8_t> enclaveIdentity,
    std::uint64_t issuedAtUnixMs,
    std::uint64_t expiresAtUnixMs,
    std::span<const std::uint8_t> evidenceHash)
{
    CertificateStore store;
    auto certificate = findSigningCertificate(store);
    auto validatorIdentity = certificateIdentity(certificate.handle);
    const auto canonical = canonicalStatement(
        transcriptHash,
        enclaveIdentity,
        issuedAtUnixMs,
        expiresAtUnixMs,
        evidenceHash,
        validatorIdentity);
    const auto digest = sha256(canonical);

    HCRYPTPROV_OR_NCRYPT_KEY_HANDLE keyHandle = 0;
    DWORD keySpec = 0;
    BOOL callerMustFree = FALSE;
    if (!CryptAcquireCertificatePrivateKey(
            certificate.handle,
            CRYPT_ACQUIRE_ONLY_NCRYPT_KEY_FLAG |
                CRYPT_ACQUIRE_SILENT_FLAG,
            nullptr,
            &keyHandle,
            &keySpec,
            &callerMustFree) ||
        keySpec != CERT_NCRYPT_KEY_SPEC)
    {
        throw std::runtime_error(
            "cannot acquire validator certificate signing handle");
    }

    try
    {
        BCRYPT_PSS_PADDING_INFO padding{
            BCRYPT_SHA256_ALGORITHM, sha256Bytes};
        DWORD signatureSize = 0;
        auto status = NCryptSignHash(
            static_cast<NCRYPT_KEY_HANDLE>(keyHandle),
            &padding,
            const_cast<PBYTE>(digest.data()),
            static_cast<DWORD>(digest.size()),
            nullptr,
            0,
            &signatureSize,
            NCRYPT_PAD_PSS_FLAG);
        if (status != ERROR_SUCCESS || signatureSize == 0)
        {
            throw std::runtime_error("cannot size validator signature");
        }
        std::vector<std::uint8_t> signature(signatureSize);
        status = NCryptSignHash(
            static_cast<NCRYPT_KEY_HANDLE>(keyHandle),
            &padding,
            const_cast<PBYTE>(digest.data()),
            static_cast<DWORD>(digest.size()),
            signature.data(),
            static_cast<DWORD>(signature.size()),
            &signatureSize,
            NCRYPT_PAD_PSS_FLAG);
        if (status != ERROR_SUCCESS || signatureSize != signature.size())
        {
            throw std::runtime_error("cannot create validator signature");
        }
        if (callerMustFree)
        {
            NCryptFreeObject(static_cast<NCRYPT_HANDLE>(keyHandle));
        }
        return {std::move(validatorIdentity), std::move(signature)};
    }
    catch (...)
    {
        if (callerMustFree)
        {
            NCryptFreeObject(static_cast<NCRYPT_HANDLE>(keyHandle));
        }
        throw;
    }
}

bool verifyStatement(
    std::span<const std::uint8_t> transcriptHash,
    std::span<const std::uint8_t> enclaveIdentity,
    std::uint64_t issuedAtUnixMs,
    std::uint64_t expiresAtUnixMs,
    std::span<const std::uint8_t> evidenceHash,
    std::span<const std::uint8_t> validatorIdentity,
    std::span<const std::uint8_t> signature)
{
    CertificateStore store;
    auto certificate = findSigningCertificate(store);
    const auto expectedIdentity = certificateIdentity(certificate.handle);
    if (validatorIdentity.size() != expectedIdentity.size())
    {
        return false;
    }
    std::uint8_t difference = 0;
    for (std::size_t index = 0; index < expectedIdentity.size(); ++index)
    {
        difference |= validatorIdentity[index] ^ expectedIdentity[index];
    }
    if (difference != 0)
    {
        return false;
    }

    const auto canonical = canonicalStatement(
        transcriptHash,
        enclaveIdentity,
        issuedAtUnixMs,
        expiresAtUnixMs,
        evidenceHash,
        validatorIdentity);
    const auto digest = sha256(canonical);

    BCRYPT_KEY_HANDLE publicKey = nullptr;
    if (!CryptImportPublicKeyInfoEx2(
            X509_ASN_ENCODING,
            &certificate.handle->pCertInfo->SubjectPublicKeyInfo,
            0,
            nullptr,
            &publicKey))
    {
        throw std::runtime_error("cannot import validator public key");
    }
    BCRYPT_PSS_PADDING_INFO padding{
        BCRYPT_SHA256_ALGORITHM, sha256Bytes};
    const auto status = BCryptVerifySignature(
        publicKey,
        &padding,
        const_cast<PUCHAR>(digest.data()),
        static_cast<ULONG>(digest.size()),
        const_cast<PUCHAR>(signature.data()),
        static_cast<ULONG>(signature.size()),
        BCRYPT_PAD_PSS);
    BCryptDestroyKey(publicKey);
    return status >= 0;
}
}
