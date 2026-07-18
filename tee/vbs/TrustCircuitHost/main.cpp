#include "Attestation.h"
#include "Json.h"

#include <chrono>
#include <cmath>
#include <exception>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <intrin.h>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include <veil\host\enclave_api.vtl0.h>
#include <VbsEnclave\HostApp\Stubs\Trusted.h>

namespace
{
const auto processStarted = std::chrono::steady_clock::now();

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

struct ValidationRequest
{
    ExecutionRequest execution;
    std::uint64_t executionUnixMs{};
    std::int64_t resultFixed{};
    std::uint64_t actualPrivacyCostFixed{};
    std::vector<std::uint8_t> resultHash;
    std::vector<std::uint8_t> transcriptHash;
    std::vector<std::uint8_t> enclaveIdentity;
    std::vector<std::uint8_t> attestationEvidence;
};

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
        throw std::runtime_error("input file is too large for the host path");
    }

    std::vector<std::uint8_t> bytes(static_cast<std::size_t>(end));
    stream.seekg(0, std::ios::beg);
    if (!bytes.empty() &&
        !stream.read(
            reinterpret_cast<char*>(bytes.data()),
            static_cast<std::streamsize>(bytes.size())))
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
    if (!value.empty() &&
        !stream.read(value.data(), static_cast<std::streamsize>(value.size())))
    {
        throw std::runtime_error("cannot read request JSON");
    }
    return value;
}

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

ExecutionRequest parseCommonExecutionRequest(
    const trustcircuit::json::Object& object)
{
    ExecutionRequest request;
    request.requestId =
        trustcircuit::json::requireString(object, "request_id");
    request.assetId = trustcircuit::json::requireString(object, "asset_id");
    request.consumerId =
        trustcircuit::json::requireString(object, "consumer_id");
    request.policyHash =
        trustcircuit::json::requireString(object, "policy_hash");
    request.policyVersion =
        trustcircuit::json::requireUint64(object, "policy_version");
    const auto functionId =
        trustcircuit::json::requireUint64(object, "function_id");
    if (functionId > (std::numeric_limits<std::uint32_t>::max)())
    {
        throw std::runtime_error("function_id is out of range");
    }
    request.functionId = static_cast<std::uint32_t>(functionId);
    request.epsilonRequested =
        trustcircuit::json::requireNumber(object, "epsilon_requested");
    request.deltaRequested =
        trustcircuit::json::requireNumber(object, "delta_requested");
    request.epsilonRequestedFixed = trustcircuit::json::requireUint64(
        object, "epsilon_requested_fixed");
    request.deltaRequestedFixed = trustcircuit::json::requireUint64(
        object, "delta_requested_fixed");
    request.encryptedPayloadPath = trustcircuit::json::requireString(
        object, "encrypted_payload_path");
    request.aad = decodeHex(
        trustcircuit::json::requireString(object, "aad"));
    request.expectedDataHash = decodeHex(
        trustcircuit::json::requireString(object, "data_hash"));
    request.lowerBoundFixed =
        trustcircuit::json::requireInt64(object, "lower_bound_fixed");
    request.upperBoundFixed =
        trustcircuit::json::requireInt64(object, "upper_bound_fixed");
    request.deadlineUnixMs =
        trustcircuit::json::requireUint64(object, "deadline_unix_ms");
    request.applyDp =
        trustcircuit::json::requireBoolean(object, "apply_dp");

    if (!std::isfinite(request.epsilonRequested) ||
        !std::isfinite(request.deltaRequested) ||
        request.epsilonRequested < 0 || request.deltaRequested < 0)
    {
        throw std::runtime_error("invalid privacy parameters");
    }
    if (!request.applyDp &&
        (request.epsilonRequestedFixed != 0 ||
         request.deltaRequestedFixed != 0))
    {
        throw std::runtime_error(
            "non-DP test requests must use zero privacy parameters");
    }
    if (request.applyDp)
    {
        if (request.epsilonRequested <= 0 ||
            request.epsilonRequested > 1.0L ||
            request.deltaRequested <= 0 || request.deltaRequested >= 1.0L)
        {
            throw std::runtime_error("DP parameters are outside supported bounds");
        }
        const auto expectedEpsilonFixed = static_cast<std::uint64_t>(
            std::ceil(request.epsilonRequested * 1000000.0L));
        const auto expectedDeltaFixed = static_cast<std::uint64_t>(
            std::ceil(request.deltaRequested * 1000000000000.0L));
        if (request.epsilonRequestedFixed != expectedEpsilonFixed ||
            request.deltaRequestedFixed != expectedDeltaFixed)
        {
            throw std::runtime_error("privacy fixed-point fields are inconsistent");
        }
    }
    return request;
}

ExecutionRequest parseExecutionRequest(
    const trustcircuit::json::Object& object)
{
    if (trustcircuit::json::requireString(object, "operation") != "execute")
    {
        throw std::runtime_error("unsupported JSON operation");
    }
    auto request = parseCommonExecutionRequest(object);
    request.key = decodeHex(
        trustcircuit::json::requireString(object, "key_hex"));
    request.nonce = decodeHex(
        trustcircuit::json::requireString(object, "nonce"));
    request.authenticationTag = decodeHex(
        trustcircuit::json::requireString(object, "authentication_tag"));
    return request;
}

ValidationRequest parseValidationRequest(
    const trustcircuit::json::Object& object)
{
    if (trustcircuit::json::requireString(object, "operation") !=
        "validate_attestation")
    {
        throw std::runtime_error("unsupported JSON operation");
    }
    ValidationRequest request;
    request.execution = parseCommonExecutionRequest(object);
    request.executionUnixMs = trustcircuit::json::requireUint64(
        object, "execution_unix_ms");
    request.resultFixed =
        trustcircuit::json::requireInt64(object, "result_fixed");
    request.actualPrivacyCostFixed = trustcircuit::json::requireUint64(
        object, "actual_privacy_cost_fixed");
    request.resultHash = decodeHex(
        trustcircuit::json::requireString(object, "result_hash"));
    request.transcriptHash = decodeHex(
        trustcircuit::json::requireString(object, "transcript_hash"));
    request.enclaveIdentity = decodeHex(
        trustcircuit::json::requireString(object, "enclave_identity"));
    request.attestationEvidence = decodeHex(
        trustcircuit::json::requireString(
            object, "native_attestation_evidence"));
    return request;
}

std::uint64_t currentUnixMilliseconds()
{
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::system_clock::now().time_since_epoch())
            .count());
}

std::uint64_t elapsedMicroseconds(
    std::chrono::steady_clock::time_point started)
{
    return static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::microseconds>(
            std::chrono::steady_clock::now() - started)
            .count());
}

std::string formatFixed(std::int64_t value)
{
    const bool negative = value < 0;
    const auto magnitude = negative
        ? static_cast<std::uint64_t>(-(value + 1)) + 1
        : static_cast<std::uint64_t>(value);
    std::ostringstream output;
    if (negative)
    {
        output << '-';
    }
    output << magnitude / 1000000ULL << '.' << std::setw(6)
           << std::setfill('0') << magnitude % 1000000ULL;
    return output.str();
}

void wipe(std::vector<std::uint8_t>& value)
{
    volatile std::uint8_t* current = value.data();
    for (std::size_t index = 0; index < value.size(); ++index)
    {
        current[index] = 0;
    }
}

void writeErrorJson(const std::string& requestId)
{
    std::cout
        << "{\"ok\":false,\"request_id\":\""
        << trustcircuit::json::escape(requestId)
        << "\",\"result\":null,\"result_hash\":null,"
           "\"actual_privacy_cost_fixed\":null,"
           "\"transcript_hash\":null,\"attestation_evidence\":null,"
           "\"timings_us\":null,\"error\":\"request rejected\"}\n";
}
}

int main(int argc, char* argv[])
{
    const bool jsonMode = argc == 2 && argv[1][0] != '-';
    std::string requestId;
    try
    {
        auto ownerId = veil::vtl0::appmodel::owner_id();
        constexpr int enclaveCreateFlags{
#ifdef _DEBUG
            ENCLAVE_VBS_FLAG_DEBUG
#endif
        };

#ifndef _DEBUG
        static_assert(
            (enclaveCreateFlags & ENCLAVE_VBS_FLAG_DEBUG) == 0,
            "Debug enclave flag must not be enabled in release builds");
#endif

        auto enclave = veil::vtl0::enclave::create(
            ENCLAVE_TYPE_VBS,
            ownerId,
            enclaveCreateFlags,
            veil::vtl0::enclave::megabytes(512));
        veil::vtl0::enclave::load_image(
            enclave.get(), L"TrustCircuitEnclave.dll");
        veil::vtl0::enclave::initialize(enclave.get(), 1);
        veil::vtl0::enclave_api::register_callbacks(enclave.get());

        auto enclaveInterface =
            VbsEnclave::Trusted::Stubs::TrustCircuitEnclave(enclave.get());
        THROW_IF_FAILED(enclaveInterface.RegisterVtl0Callbacks());

        if (argc == 1)
        {
            std::cout << "Hello World!\n";
            const auto result = enclaveInterface.DoSecretMath(10, 20);
            std::cout << "Result = " << result << "\n";
            return result == 200 ? 0 : 1;
        }

        if (jsonMode)
        {
            const auto object = trustcircuit::json::parseObject(
                loadTextFile(argv[1]));
            const auto operation = trustcircuit::json::requireString(
                object, "operation");
            if (operation == "execute")
            {
            const auto hostTotalStarted = std::chrono::steady_clock::now();
            auto request = parseExecutionRequest(object);
            requestId = request.requestId;
            auto wipeKey = wil::scope_exit([&request] { wipe(request.key); });
            const auto ciphertext = loadBinaryFile(
                std::filesystem::path(request.encryptedPayloadPath));
            const auto executionUnixMs = currentUnixMilliseconds();
            const auto processStartupUs = elapsedMicroseconds(processStarted);

            std::int64_t resultFixed = 0;
            std::uint64_t rowCount = 0;
            std::uint64_t actualPrivacyCostFixed = 0;
            std::vector<std::uint8_t> resultHash;
            std::vector<std::uint8_t> transcriptHash;
            std::vector<std::uint8_t> enclaveIdentity;
            std::vector<std::uint8_t> attestationEvidence;
            std::uint64_t decryptUs = 0;
            std::uint64_t hashUs = 0;
            std::uint64_t aggregateUs = 0;
            std::uint64_t dpNoiseUs = 0;
            std::uint64_t transcriptUs = 0;
            std::uint64_t attestationUs = 0;
            const auto enclaveCallStarted = std::chrono::steady_clock::now();
            THROW_IF_FAILED(enclaveInterface.ExecuteEncrypted(
                ciphertext,
                request.key,
                request.nonce,
                request.authenticationTag,
                request.aad,
                request.expectedDataHash,
                request.requestId,
                request.assetId,
                request.consumerId,
                request.policyHash,
                request.encryptedPayloadPath,
                request.policyVersion,
                request.functionId,
                request.epsilonRequestedFixed,
                request.deltaRequestedFixed,
                request.lowerBoundFixed,
                request.upperBoundFixed,
                request.deadlineUnixMs,
                executionUnixMs,
                request.applyDp,
                calibrateTscTicksPerMicrosecond(),
                resultFixed,
                rowCount,
                actualPrivacyCostFixed,
                resultHash,
                transcriptHash,
                enclaveIdentity,
                attestationEvidence,
                decryptUs,
                hashUs,
                aggregateUs,
                dpNoiseUs,
                transcriptUs,
                attestationUs));
            const auto enclaveCallUs = elapsedMicroseconds(enclaveCallStarted);
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
                << "\",\"enclave_identity\":\""
                << encodeHex(enclaveIdentity)
                << "\",\"execution_unix_ms\":" << executionUnixMs
                << ",\"native_attestation_evidence\":\""
                << encodeHex(attestationEvidence)
                << "\",\"attestation_evidence\":null,\"row_count\":"
                << rowCount << ",\"timings_us\":{\"host_total\":"
                << hostTotalUs << ",\"process_startup\":"
                << processStartupUs << ",\"enclave_call\":"
                << enclaveCallUs << ",\"decrypt\":" << decryptUs
                << ",\"hash\":" << hashUs << ",\"aggregate\":"
                << aggregateUs << ",\"dp_noise\":" << dpNoiseUs
                << ",\"transcript\":" << transcriptUs
                << ",\"attestation\":" << attestationUs
                << "},\"error\":null}\n";
            return 0;
            }

            if (operation == "validate_attestation")
            {
                const auto hostTotalStarted = std::chrono::steady_clock::now();
                auto request = parseValidationRequest(object);
                requestId = request.execution.requestId;
                std::vector<std::uint8_t> validatedTranscriptHash;
                std::vector<std::uint8_t> validatedEnclaveIdentity;
                std::vector<std::uint8_t> evidenceHash;
                std::uint64_t issuedAtUnixMs = 0;
                std::uint64_t expiresAtUnixMs = 0;
                std::uint64_t validationUs = 0;
                const auto enclaveCallStarted =
                    std::chrono::steady_clock::now();
                THROW_IF_FAILED(
                    enclaveInterface.ValidateAttestationEvidence(
                        request.attestationEvidence,
                        request.execution.aad,
                        request.execution.expectedDataHash,
                        request.execution.requestId,
                        request.execution.assetId,
                        request.execution.consumerId,
                        request.execution.policyHash,
                        request.execution.encryptedPayloadPath,
                        request.execution.policyVersion,
                        request.execution.functionId,
                        request.execution.epsilonRequestedFixed,
                        request.execution.deltaRequestedFixed,
                        request.execution.lowerBoundFixed,
                        request.execution.upperBoundFixed,
                        request.execution.deadlineUnixMs,
                        request.executionUnixMs,
                        request.execution.applyDp,
                        request.resultFixed,
                        request.actualPrivacyCostFixed,
                        request.resultHash,
                        request.transcriptHash,
                        request.enclaveIdentity,
                        currentUnixMilliseconds(),
                        calibrateTscTicksPerMicrosecond(),
                        validatedTranscriptHash,
                        validatedEnclaveIdentity,
                        evidenceHash,
                        issuedAtUnixMs,
                        expiresAtUnixMs,
                        validationUs));
                const auto enclaveCallUs =
                    elapsedMicroseconds(enclaveCallStarted);
                const auto statementSignature =
                    trustcircuit::attestation::signStatement(
                        validatedTranscriptHash,
                        validatedEnclaveIdentity,
                        issuedAtUnixMs,
                        expiresAtUnixMs,
                        evidenceHash);
                if (!trustcircuit::attestation::verifyStatement(
                        validatedTranscriptHash,
                        validatedEnclaveIdentity,
                        issuedAtUnixMs,
                        expiresAtUnixMs,
                        evidenceHash,
                        statementSignature.validatorIdentity,
                        statementSignature.bytes))
                {
                    throw std::runtime_error(
                        "validator statement self-verification failed");
                }
                const auto hostTotalUs =
                    elapsedMicroseconds(hostTotalStarted);

                std::cout
                    << "{\"ok\":true,\"format\":"
                       "\"TrustCircuit.AttestationStatement.v1\","
                       "\"request_id\":\""
                    << trustcircuit::json::escape(request.execution.requestId)
                    << "\",\"transcript_hash\":\""
                    << encodeHex(validatedTranscriptHash)
                    << "\",\"enclave_identity\":\""
                    << encodeHex(validatedEnclaveIdentity)
                    << "\",\"issued_at_unix_ms\":" << issuedAtUnixMs
                    << ",\"expires_at_unix_ms\":" << expiresAtUnixMs
                    << ",\"validator_identity\":\""
                    << encodeHex(statementSignature.validatorIdentity)
                    << "\",\"evidence_sha256\":\""
                    << encodeHex(evidenceHash)
                    << "\",\"signature_algorithm\":\""
                    << trustcircuit::attestation::signatureAlgorithm
                    << "\",\"signature\":\""
                    << encodeHex(statementSignature.bytes)
                    << "\",\"native_verification\":"
                       "\"EnclaveVerifyAttestationReport\","
                       "\"timings_us\":{\"host_total\":"
                    << hostTotalUs << ",\"enclave_call\":"
                    << enclaveCallUs << ",\"attestation_validation\":"
                    << validationUs << "},\"error\":null}\n";
                return 0;
            }
            throw std::runtime_error("unsupported JSON operation");
        }

        std::vector<std::uint8_t> input;
        if (argc == 3 && std::string(argv[1]) == "--hash-file")
        {
            input = loadBinaryFile(argv[2]);
        }
        else if (argc == 3 && std::string(argv[1]) == "--hash-hex")
        {
            input = decodeHex(argv[2]);
        }
        else if (argc == 6 && std::string(argv[1]) == "--aggregate-file")
        {
            input = loadBinaryFile(argv[2]);
            const std::string functionName(argv[3]);
            const std::uint32_t functionId = functionName == "COUNT"
                ? 1U
                : functionName == "MEAN" ? 2U : 0U;
            const auto lowerBoundFixed = std::stoll(argv[4]);
            const auto upperBoundFixed = std::stoll(argv[5]);
            std::int64_t resultFixed = 0;
            std::uint64_t rowCount = 0;
            std::uint64_t aggregateUs = 0;
            THROW_IF_FAILED(enclaveInterface.AggregateDataset(
                input,
                functionId,
                lowerBoundFixed,
                upperBoundFixed,
                calibrateTscTicksPerMicrosecond(),
                resultFixed,
                rowCount,
                aggregateUs));
            std::cout << "ResultFixed = " << resultFixed << "\n"
                      << "Rows = " << rowCount << "\n"
                      << "AggregateUs = " << aggregateUs << "\n";
            return 0;
        }
        else
        {
            throw std::runtime_error(
                "usage: TrustCircuitHost.exe [REQUEST.json|--hash-file PATH|"
                "--hash-hex HEX|--aggregate-file PATH COUNT|MEAN "
                "LOWER_FIXED UPPER_FIXED]");
        }

        std::vector<std::uint8_t> digest;
        THROW_IF_FAILED(enclaveInterface.HashBuffer(input, digest));
        std::cout << "Hash = " << encodeHex(digest) << "\n";
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "TrustCircuitHost failed: " << error.what() << "\n";
        if (jsonMode)
        {
            writeErrorJson(requestId);
        }
        return 1;
    }
    catch (...)
    {
        std::cerr << "TrustCircuitHost failed with an unknown error\n";
        if (jsonMode)
        {
            writeErrorJson(requestId);
        }
        return 1;
    }
}
