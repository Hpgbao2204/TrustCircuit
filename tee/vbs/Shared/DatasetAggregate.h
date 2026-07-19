#pragma once

#include <algorithm>
#include <cstdint>
#include <intrin.h>
#include <limits>
#include <span>
#include <vector>

namespace trustcircuit::processing
{
inline constexpr std::size_t datasetHeaderBytes = 16;
inline constexpr std::uint32_t datasetVersion = 1;
inline constexpr std::uint32_t maxDatasetRows = 100000;
inline constexpr std::int64_t fixedPointScale = 1000000;
inline constexpr std::uint32_t functionCount = 1;
inline constexpr std::uint32_t functionMean = 2;
inline constexpr std::uint8_t datasetMagic[8] = {
    'T', 'C', 'V', 'B', 'S', 'D', 'S', '1'};

inline std::uint32_t readUint32LittleEndian(
    std::span<const std::uint8_t> input,
    std::size_t offset)
{
    return static_cast<std::uint32_t>(input[offset]) |
        (static_cast<std::uint32_t>(input[offset + 1]) << 8) |
        (static_cast<std::uint32_t>(input[offset + 2]) << 16) |
        (static_cast<std::uint32_t>(input[offset + 3]) << 24);
}

inline std::int64_t readInt64LittleEndian(
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

// This is the single native/enclave implementation of the TCVBSDS1 parser,
// bounds checks, COUNT, and MEAN. Timing is returned from the same TSC path in
// both builds; it is performance metadata and never a security input.
inline HRESULT aggregateDataset(
    const std::vector<std::uint8_t>& payload,
    std::uint32_t functionId,
    std::int64_t lowerBoundFixed,
    std::int64_t upperBoundFixed,
    std::uint64_t tscTicksPerUs,
    std::int64_t& resultFixed,
    std::uint64_t& rowCount,
    std::uint64_t& aggregateUs)
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
}
