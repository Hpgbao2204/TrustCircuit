#include <exception>
#include <iostream>

#include <veil\host\enclave_api.vtl0.h>
#include <VbsEnclave\HostApp\Stubs\Trusted.h>

int main()
{
    try
    {
        std::cout << "Hello World!\n";

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
        veil::vtl0::enclave::load_image(enclave.get(), L"TrustCircuitEnclave.dll");
        veil::vtl0::enclave::initialize(enclave.get(), 1);
        veil::vtl0::enclave_api::register_callbacks(enclave.get());

        auto enclaveInterface = VbsEnclave::Trusted::Stubs::TrustCircuitEnclave(enclave.get());
        THROW_IF_FAILED(enclaveInterface.RegisterVtl0Callbacks());

        const auto result = enclaveInterface.DoSecretMath(10, 20);
        std::cout << "Result = " << result << "\n";
        return result == 200 ? 0 : 1;
    }
    catch (const std::exception& error)
    {
        std::cerr << "TrustCircuitHost failed: " << error.what() << "\n";
        return 1;
    }
    catch (...)
    {
        std::cerr << "TrustCircuitHost failed with an unknown error\n";
        return 1;
    }
}
