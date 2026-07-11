cmake_minimum_required(VERSION 3.22.0)

project(vs-dfttest2 VERSION 10.0 LANGUAGES CXX)

set(ENABLE_CUDA OFF CACHE BOOL "Whether to compile with cuFFT backend")
set(ENABLE_NVRTC ON CACHE BOOL "Whether to compile with NVRTC backend")
set(ENABLE_CPU ON CACHE BOOL "Whether to compile with x86 backend")
set(ENABLE_GCC OFF CACHE BOOL "Whether to compile with gcc vector extension backend")
set(ENABLE_HIP OFF CACHE BOOL "Whether to compile with HIP backends")

if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "Choose the type of build" FORCE)
endif()

if(ENABLE_CUDA OR ENABLE_NVRTC)
    set(USE_NVRTC_STATIC ON CACHE BOOL "Whether to use NVRTC static library")

    find_package(CUDAToolkit REQUIRED)
endif()

if(ENABLE_CUDA)
    add_library(dfttest2_cuda MODULE
        cuda_source/source.cpp
        cuda_source/win32.cpp
    )

    set_target_properties(dfttest2_cuda PROPERTIES
        CXX_EXTENSIONS OFF
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED ON
    )

    target_link_libraries(dfttest2_cuda PRIVATE CUDA::cuda_driver CUDA::cufft)

    if(WIN32 AND MSVC)
        math(EXPR CUDA_CUFFT_DLL_MAJOR "${CUDAToolkit_VERSION_MAJOR} - 1")
        set(CUDA_CUFFT_DELAYLOAD_DLL "cufft64_${CUDA_CUFFT_DLL_MAJOR}.dll")
        target_link_libraries(dfttest2_cuda PRIVATE delayimp)
        target_link_options(dfttest2_cuda PRIVATE "/DELAYLOAD:nvcuda.dll" "/DELAYLOAD:${CUDA_CUFFT_DELAYLOAD_DLL}")
    endif()
endif()

if(ENABLE_NVRTC)
    add_library(dfttest2_nvrtc MODULE
        nvrtc_source/source.cpp
    )

    set_target_properties(dfttest2_nvrtc PROPERTIES
        CXX_EXTENSIONS OFF
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED ON
    )

    target_link_libraries(dfttest2_nvrtc PRIVATE CUDA::cuda_driver)

    if(WIN32 AND MSVC)
        target_link_libraries(dfttest2_nvrtc PRIVATE delayimp)
        target_link_options(dfttest2_nvrtc PRIVATE "/DELAYLOAD:nvcuda.dll")
    endif()
endif()

if(ENABLE_CUDA OR ENABLE_NVRTC)
    if(
        USE_NVRTC_STATIC AND (
            CUDAToolkit_VERSION_MAJOR GREATER_EQUAL "12" OR (
                CUDAToolkit_VERSION_MAJOR EQUAL "11" AND
                CUDAToolkit_VERSION_MINOR GREATER_EQUAL "5"
            )
        )
    )
        set(static_nvrtc_targets)
        if(TARGET dfttest2_cuda)
            list(APPEND static_nvrtc_targets dfttest2_cuda)
        endif()
        if(TARGET dfttest2_nvrtc)
            list(APPEND static_nvrtc_targets dfttest2_nvrtc)
        endif()

        foreach(static_nvrtc_target IN LISTS static_nvrtc_targets)
            if(TARGET CUDA::nvrtc_static)
                target_link_libraries(${static_nvrtc_target} PRIVATE CUDA::nvrtc_static)

                foreach(optional_cuda_static_target IN ITEMS
                    CUDA::nvrtc_builtins_static
                    CUDA::nvptxcompiler_static
                    CUDA::nvJitLink_static
                    CUDA::nvfatbin_static
                )
                    if(TARGET ${optional_cuda_static_target})
                        target_link_libraries(${static_nvrtc_target} PRIVATE ${optional_cuda_static_target})
                    endif()
                endforeach()
            else()
                target_link_directories(${static_nvrtc_target} PRIVATE "${CUDAToolkit_LIBRARY_DIR}")
                target_link_libraries(${static_nvrtc_target} PRIVATE nvrtc_static nvrtc-builtins_static nvptxcompiler_static)

                foreach(optional_cuda_static_library IN ITEMS nvJitLink_static nvfatbin_static)
                    find_library(${optional_cuda_static_library}_LIBRARY
                        NAMES ${optional_cuda_static_library}
                        PATHS "${CUDAToolkit_LIBRARY_DIR}"
                        NO_DEFAULT_PATH
                    )
                    if(${optional_cuda_static_library}_LIBRARY)
                        target_link_libraries(${static_nvrtc_target} PRIVATE "${${optional_cuda_static_library}_LIBRARY}")
                    endif()
                endforeach()
            endif()
        endforeach()

        if(CMAKE_CXX_COMPILER_ID STREQUAL "MSVC")
            foreach(static_nvrtc_target IN LISTS static_nvrtc_targets)
                set_property(TARGET ${static_nvrtc_target} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded")
            endforeach()
        endif()

        if(CMAKE_SYSTEM_NAME STREQUAL "Windows")
            foreach(static_nvrtc_target IN LISTS static_nvrtc_targets)
                target_link_libraries(${static_nvrtc_target} PRIVATE Ws2_32)
            endforeach()
        endif()
    else()
        if(USE_NVRTC_STATIC)
            message(WARNING "NVRTC static library is not used")
        endif()
        if(TARGET dfttest2_cuda)
            target_link_libraries(dfttest2_cuda PRIVATE CUDA::nvrtc)
        endif()
        if(TARGET dfttest2_nvrtc)
            target_link_libraries(dfttest2_nvrtc PRIVATE CUDA::nvrtc)
        endif()
    endif()
endif() # ENABLE_CUDA OR ENABLE_NVRTC

if(ENABLE_HIP)
    find_package(hip REQUIRED config)
    find_package(hipfft REQUIRED config)
    find_package(hiprtc REQUIRED config)

    add_library(dfttest2_hip MODULE
        hip_source/source.cpp
    )
    add_library(dfttest2_hiprtc MODULE
        hiprtc_source/source.cpp
    )

    set_target_properties(dfttest2_hip PROPERTIES
        CXX_EXTENSIONS OFF
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED ON
    )
    set_target_properties(dfttest2_hiprtc PROPERTIES
        CXX_EXTENSIONS OFF
        CXX_STANDARD 20
        CXX_STANDARD_REQUIRED ON
    )

    target_link_libraries(dfttest2_hip PRIVATE hip::host hip::hipfft hiprtc::hiprtc)
    target_link_libraries(dfttest2_hiprtc PRIVATE hip::host hiprtc::hiprtc)
endif() # ENABLE_HIP

find_package(PkgConfig QUIET MODULE)

if(PKG_CONFIG_FOUND)
    pkg_search_module(VS vapoursynth)

    if(VS_FOUND)
        message(STATUS "Found VapourSynth r${VS_VERSION}")

        cmake_path(APPEND install_dir ${VS_LIBDIR} vapoursynth)

        if(TARGET dfttest2_cuda)
            target_include_directories(dfttest2_cuda PRIVATE ${VS_INCLUDE_DIRS})
            install(TARGETS dfttest2_cuda LIBRARY DESTINATION ${install_dir} RUNTIME DESTINATION ${install_dir})
        endif()
        if(TARGET dfttest2_nvrtc)
            target_include_directories(dfttest2_nvrtc PRIVATE ${VS_INCLUDE_DIRS})
            install(TARGETS dfttest2_nvrtc LIBRARY DESTINATION ${install_dir} RUNTIME DESTINATION ${install_dir})
        endif()

        if(ENABLE_HIP)
            target_include_directories(dfttest2_hip PRIVATE ${VS_INCLUDE_DIRS})
            target_include_directories(dfttest2_hiprtc PRIVATE ${VS_INCLUDE_DIRS})

            install(TARGETS dfttest2_hip LIBRARY DESTINATION ${install_dir})
            install(TARGETS dfttest2_hiprtc LIBRARY DESTINATION ${install_dir})
        endif() # ENABLE_HIP
    endif()
endif()

if(NOT VS_FOUND)
    set(VS_INCLUDE_DIR "" CACHE PATH "Path to VapourSynth headers")

    if(VS_INCLUDE_DIR STREQUAL "")
        message(WARNING "VapourSynth not found")
    endif()

    if(TARGET dfttest2_cuda)
        target_include_directories(dfttest2_cuda PRIVATE ${VS_INCLUDE_DIR})
        install(TARGETS dfttest2_cuda LIBRARY DESTINATION lib RUNTIME DESTINATION lib)
    endif()
    if(TARGET dfttest2_nvrtc)
        target_include_directories(dfttest2_nvrtc PRIVATE ${VS_INCLUDE_DIR})
        install(TARGETS dfttest2_nvrtc LIBRARY DESTINATION lib RUNTIME DESTINATION lib)
    endif()

    if(ENABLE_HIP)
        target_include_directories(dfttest2_hip PRIVATE ${VS_INCLUDE_DIR})
        target_include_directories(dfttest2_hiprtc PRIVATE ${VS_INCLUDE_DIR})

        install(TARGETS dfttest2_hip LIBRARY DESTINATION lib)
        install(TARGETS dfttest2_hiprtc LIBRARY DESTINATION lib)
    endif() # ENABLE_HIP
endif()

find_package(Git QUIET)

if(GIT_FOUND)
    execute_process(
        COMMAND ${GIT_EXECUTABLE} describe --tags --long --always
        WORKING_DIRECTORY "${CMAKE_SOURCE_DIR}"
        OUTPUT_VARIABLE VCS_TAG
    )
    if(VCS_TAG)
        string(STRIP ${VCS_TAG} VCS_TAG)
    endif()
endif()

if(VCS_TAG)
    message(STATUS "vs-dfttest2 ${VCS_TAG}")
else()
    message(WARNING "unknown plugin version")
    set(VCS_TAG "unknown")
endif()

configure_file(common/config.h.in config.h)

if(TARGET dfttest2_cuda)
    target_include_directories(dfttest2_cuda PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
endif()

if(TARGET dfttest2_nvrtc)
    target_include_directories(dfttest2_nvrtc PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
endif()

if(ENABLE_CPU)
    add_subdirectory(cpu_source)
endif() # ENABLE_CPU

if(ENABLE_GCC)
    add_subdirectory(gcc_source)
endif() # ENABLE_GCC

if(ENABLE_HIP)
    target_include_directories(dfttest2_hip PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
    target_include_directories(dfttest2_hiprtc PRIVATE ${CMAKE_CURRENT_BINARY_DIR})
endif() # ENABLE_HIP
