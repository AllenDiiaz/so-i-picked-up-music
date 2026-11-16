# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.22)

# The DSP of experiment 07 as is (one copy of emg_dsp.c for 07, 08, 10, 11 and the host tools),
# plus this experiment's own "coach" component (command parser, scaled hard threshold).
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../07_onboard_tension/components"
                         "${CMAKE_CURRENT_LIST_DIR}/components")

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(coach_loop)
