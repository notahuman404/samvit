cmake_minimum_required(VERSION 3.16)
project(haptic_vest VERSION 1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# librealsense2
find_package(realsense2 REQUIRED)

add_executable(haptic_vest
    main.cpp
    connector.cpp
    camera_fusion.cpp
    depth_processing.cpp
    motor_driver.cpp
)

target_link_libraries(haptic_vest PRIVATE
    realsense2::realsense2
    pthread
)

target_include_directories(haptic_vest PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

install(TARGETS haptic_vest DESTINATION bin)
