#pragma once

#include <cstdint>
#include <span>
#include <string_view>
#include <vector>

namespace trustcircuit::attestation
{
inline constexpr std::string_view signatureAlgorithm =
    "RSASSA-PSS-SHA256";

struct Signature
{
    std::vector<std::uint8_t> validatorIdentity;
    std::vector<std::uint8_t> bytes;
};

Signature signStatement(
    std::span<const std::uint8_t> transcriptHash,
    std::span<const std::uint8_t> enclaveIdentity,
    std::uint64_t issuedAtUnixMs,
    std::uint64_t expiresAtUnixMs,
    std::span<const std::uint8_t> evidenceHash);

bool verifyStatement(
    std::span<const std::uint8_t> transcriptHash,
    std::span<const std::uint8_t> enclaveIdentity,
    std::uint64_t issuedAtUnixMs,
    std::uint64_t expiresAtUnixMs,
    std::span<const std::uint8_t> evidenceHash,
    std::span<const std::uint8_t> validatorIdentity,
    std::span<const std::uint8_t> signature);
}
