# SPDX-FileCopyrightText: (C) 2025 Intel Corporation
# SPDX-License-Identifier: Apache-2.0

########################################
# Edge AI Pipelines Workload
########################################

.DEFAULT_GOAL := help

# Workload variables
CONFIG ?= light
DETECT ?= CPU
CLASSIFY ?= CPU
DURATION ?= 120
CORES ?=
MODEL_INST ?= 0
POWER ?= True
WALL_POWER ?= False
CLEAR ?= False
DRY_RUN ?= False
RESUME ?= False

SUDO := $(if $(filter True true TRUE yes YES,$(POWER)),sudo,)
WALL_POWER_ENV := $(if $(filter True true TRUE yes YES,$(WALL_POWER)),WALL_POWER=True,)
VERBOSE ?= 0

# Usage
.PHONY: help
help:
	@echo ""
	@echo "Edge AI Pipelines"
	@echo "================="
	@echo ""
	@echo "Checks:"
	@echo "  make collateral             Download AI models and media files"
	@echo "  make check                  Verify all required collateral is present"
	@echo ""
	@echo "Benchmarks:"
	@echo "  make benchmarks             Sweep all benchmark configurations"
	@echo ""
	@echo "  Options:"
	@echo "    DRY_RUN                   Lists all benchmark configurations without running (default: False)"
	@echo "    RESUME                    Skip tests that already have results (default: False)"
	@echo "    DURATION                  Set the duration for each benchmark test (default: 120 seconds)"
	@echo "    POWER                     Enable/Disable power/efficiency metrics (default: True, requires sudo)"
	@echo "    WALL_POWER                Enable PDU wall power measurement (default: False, requires config in utils/helper_functions.sh)"
	@echo "    MODEL_INST                Number of model instances for round-robin stream distribution (default: 0 = disabled)"
	@echo "    CORES                     Pin the cores for scheduling workload.  (default: all cores)"
	@echo "                              Accepts the following: pcore, ecore, and min-max range (example: 0-11)"
	@echo "                              Performance and efficiency may vary depending on core pinning"
	@echo ""
	@echo "Display Demo:"
	@echo "  make display                Optional: Visualized pipeline demo (requires display access)"
	@echo ""
	@echo "  Options:"
	@echo "    CONFIG                    Pipeline configuration (light, medium, or heavy)"
	@echo "    DETECT                    Inference Device for Detection (CPU|GPU|NPU)"
	@echo "    CLASSIFY                  Inference Device for Classification (CPU|GPU|NPU)"
	@echo ""
	@echo "Cleanup:"
	@echo "  sudo make clean             Optional: Remove all results"
	@echo ""

.PHONY: check-collateral
check-collateral:
	@$(MAKE) --no-print-directory -C ../../tools/model-conversion verify VERBOSE=$(VERBOSE)
	@echo ""
	@$(MAKE) --no-print-directory -C ../../tools/media-downloader verify VERBOSE=$(VERBOSE)

.PHONY: check
check:
	@echo "Edge AI Pipelines — Collateral Check"
	@echo "====================================="
	@echo ""
	@bash ../../utils/verify_collateral.sh --section vision --verbose || true
	@echo ""
	@bash ../../utils/verify_collateral.sh --section media --verbose || true

.PHONY: collateral
collateral:
	@$(MAKE) --no-print-directory -C ../.. collateral INCLUDE_VISION=True INCLUDE_MEDIA=True INCLUDE_GENAI=False

.PHONY: display
display: check-collateral
	@echo "[ Info ] Launching display pipeline: config=$(CONFIG) detect=$(DETECT) classify=$(CLASSIFY) duration=$(DURATION) cores=$(CORES)"
	./display_pipeline.sh -p $(CONFIG) -d $(DETECT) -c $(CLASSIFY) -i $(DURATION) $(if $(CORES),-t $(CORES),)

# Benchmark sweep using dynamic coverage matrix generation
# 8 Streams ran during workload runtime. Theoretical stream density calculated as Total Throughput / Target FPS.

.PHONY: benchmarks
benchmarks: check-collateral
	@if echo "$(CLEAR)" | grep -qiE '^(true|yes)$$'; then $(MAKE) clean; fi
	@echo "[ Info ] Generating benchmark coverage matrix..."
	@coverage_output=$$(./pipeline-utils/generate_benchmark_coverage.sh); \
	total_tests=$$(echo "$$coverage_output" | grep "^TOTAL_TESTS=" | cut -d= -f2); \
	total_time_s=$$(( total_tests * ($(DURATION) + 10) )); \
	total_time_m=$$(( total_time_s / 60 )); \
	echo "[ Info ] Benchmark sweep: $$total_tests tests, ~$${total_time_m}m estimated$(if $(CORES), core pinning: $(CORES),)"; \
	echo ""; \
	if echo "$(DRY_RUN)" | grep -qiE '^(true|yes)$$'; then \
		echo "[ Dry Run ] Coverage matrix:"; \
		echo "$$coverage_output" | grep -v "^#" | grep -v "^TOTAL_TESTS="; \
		echo ""; \
		echo "[ Dry Run ] $$total_tests tests × $(DURATION)s + 10s cooldown = ~$${total_time_m}m total"; \
		exit 0; \
	fi; \
	current=0; \
	ran=0; \
	start_epoch=$$(date +%s); \
	cores_opt="$(if $(CORES),-t $(CORES),)"; \
	echo "$$coverage_output" | grep -v "^#" | grep -v "^TOTAL_TESTS=" | while IFS=, read -r cfg det cls batch concurrent; do \
		current=$$((current + 1)); \
		if echo "$(RESUME)" | grep -qiE '^(true|yes)$$'; then \
			existing=$$(find ../../collateral/results/edge-ai-pipelines -name "e2e-edge-pipeline_$${cfg}_*_$${det}-Det_$${cls}-Class_BS$${batch}_*.csv" 2>/dev/null | head -1); \
			if [ -n "$$existing" ]; then \
				echo "[ Info ] [$$current/$$total_tests] Skipping (resume): $$cfg $$det/$$cls BS$$batch — results exist"; \
				continue; \
			fi; \
		fi; \
		pct=$$((current * 100 / total_tests)); \
		now_epoch=$$(date +%s); \
		elapsed=$$((now_epoch - start_epoch)); \
		if [ $$ran -gt 0 ] && [ $$elapsed -gt 0 ]; then \
			rate_ms=$$((elapsed * 1000 / ran)); \
			remaining_ms=$$(( (total_tests - current) * rate_ms )); \
			eta_m=$$((remaining_ms / 60000)); \
			eta_s=$$(( (remaining_ms / 1000) % 60 )); \
			eta_str="ETA: $${eta_m}m$${eta_s}s"; \
		else \
			eta_str="ETA: calculating..."; \
		fi; \
		filled=$$((pct / 5)); \
		empty=$$((20 - filled)); \
		bar="$$(printf '%0.s█' $$(seq 1 $$filled 2>/dev/null))$$(printf '%0.s░' $$(seq 1 $$empty 2>/dev/null))"; \
		mode_desc="$$( [ -n "$$concurrent" ] && echo " (concurrent)" || echo "" )"; \
		echo "[ Info ] [$$current/$$total_tests] $$bar $${pct}%% | $$eta_str | cfg=$$cfg det=$$det cls=$$cls BS$$batch$$mode_desc"; \
		$(SUDO) $(WALL_POWER_ENV) ./benchmark_edge_pipelines.sh -p $$cfg -n 8 -b $$batch -d $$det -c $$cls -i $(DURATION) -m $(MODEL_INST) $$concurrent $$cores_opt || { \
			echo "[ FAILED ] Benchmark run failed (cfg=$$cfg det=$$det cls=$$cls batch=$$batch $$concurrent)"; \
			continue; \
		}; \
		echo "[ Info ] Sleeping for 10 seconds to prevent thermal throttling."; \
		sleep 10; \
		ran=$$((ran + 1)); \
	done; \
	elapsed_total=$$(( $$(date +%s) - start_epoch )); \
	elapsed_m=$$((elapsed_total / 60)); \
	elapsed_s=$$((elapsed_total % 60)); \
	echo ""; \
	echo "[ Info ] Completed $$total_tests benchmark runs in $${elapsed_m}m$${elapsed_s}s."

.PHONY: clean
clean:
	@echo "[ Info ] Cleaning results directory (logs & CSV)."
	@find ../../collateral/results/edge-ai-pipelines -type f \( -name "*.log" -o -name "*.csv" \) -delete 2>/dev/null || true
