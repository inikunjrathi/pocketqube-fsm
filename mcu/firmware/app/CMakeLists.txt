cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(cepdt_mcu_app)

target_sources(app PRIVATE src/main.c)

target_sources(app PRIVATE src/engine_config_table.c)

target_sources(app PRIVATE src/engine_guards.c)

target_sources(app PRIVATE src/engine_fsm.c)

target_sources(app PRIVATE src/engine_auth.c)

if(CEPDT_ENGINE_GROUND_AUTH_ENABLED)
  target_compile_definitions(app PRIVATE ENGINE_GROUND_AUTH_ENABLED=1)
endif()

target_sources(app PRIVATE src/engine_persistence.c)
target_sources(app PRIVATE src/engine_persistence_io_zephyr.c)

if(CEPDT_ENGINE_PERSIST_TESTHOOKS_ENABLED)
  target_compile_definitions(app PRIVATE ENGINE_PERSIST_TESTHOOKS_ENABLED=1)
endif()

target_sources(app PRIVATE src/engine_scheduler.c)

target_sources(app PRIVATE src/engine_arbitration.c src/engine_arbitration_table.c)

if(CEPDT_ENGINE_SCHED_TESTHOOKS_ENABLED)
  target_compile_definitions(app PRIVATE ENGINE_SCHED_TESTHOOKS_ENABLED=1)
endif()
