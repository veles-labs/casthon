include $(TOP)/py/mkenv.mk
QSTR_DEFS = qstrdefsport.h
include $(TOP)/py/py.mk

INC += -I. -I$(TOP) -I$(BUILD) -I$(GENERATED)
# Core objects and generated C headers are independent of frozen Python code.
# Keep per-contract objects separate so contracts can share a compiled runtime.
CONTRACT_BUILD ?= $(BUILD)
CFLAGS += $(INC) -std=c99 -Oz -flto -DNDEBUG -fwrapv -fno-jump-tables
CFLAGS += -mno-bulk-memory -mno-reference-types -mno-multivalue
CFLAGS += -mno-nontrapping-fptoint -mno-sign-ext -mno-simd128 -mno-atomics
LDFLAGS += -Oz -flto --no-entry -sSTANDALONE_WASM=1 -sFILESYSTEM=0
LDFLAGS += -sSUPPORT_LONGJMP=0 -sSTACK_SIZE=262144 -sMALLOC=emmalloc
HEAP ?= emmalloc-gc0
ifneq ($(filter emmalloc-gc0 emmalloc-gc1,$(HEAP)),)
LDFLAGS += -sINITIAL_MEMORY=4194304 -sMAXIMUM_MEMORY=4194304 -sALLOW_MEMORY_GROWTH=0 -sABORTING_MALLOC=0
ifeq ($(HEAP),emmalloc-gc0)
CFLAGS += -DCSPR_ENABLE_GC=0
else
CFLAGS += -DCSPR_ENABLE_GC=1 -DCSPR_MALLOC_GC_HEAP=1 -DCSPR_MAXIMUM_MEMORY=4194304
endif
else ifeq ($(HEAP),split)
CFLAGS += -DCSPR_ENABLE_GC=1 -DCSPR_SPLIT_HEAP=1 -DCSPR_INITIAL_HEAP_BYTES=65536 -DCSPR_MAXIMUM_MEMORY=4194304
LDFLAGS += -sINITIAL_MEMORY=524288 -sMAXIMUM_MEMORY=4194304 -sALLOW_MEMORY_GROWTH=1 -sABORTING_MALLOC=0
else ifeq ($(HEAP),static)
CFLAGS += -DCSPR_ENABLE_GC=1
LDFLAGS += -sINITIAL_MEMORY=4194304 -sALLOW_MEMORY_GROWTH=0
else
$(error Unsupported HEAP=$(HEAP))
endif
SRC_C = adapter.c system.c
ifneq ($(SOFTFLOAT_LIB),)
SRC_C += softfloat/ops.c
CFLAGS += $(SOFTFLOAT_FLAGS)
LDFLAGS += $(SOFTFLOAT_EXPORTS)
endif
SRC_QSTR += adapter.c
OBJ += $(PY_CORE_O) $(addprefix $(BUILD)/,$(SRC_C:.c=.o)) $(CONTRACT_BUILD)/entrypoints.o $(CONTRACT_BUILD)/frozen_content.o
MPY_FILES = $(wildcard $(GENERATED)/*.mpy)

all: $(CONTRACT_BUILD)/contract.raw.wasm

$(CONTRACT_BUILD)/entrypoints.o: $(GENERATED)/entrypoints.c
	$(CC) $(CFLAGS) -c $< -o $@

$(CONTRACT_BUILD)/frozen_content.c: $(MPY_FILES) $(wildcard $(GENERATED)/modules.json) $(BUILD)/genhdr/qstrdefs.generated.h
	$(PYTHON) $(TOP)/tools/mpy-tool.py -f -q $(BUILD)/genhdr/qstrdefs.preprocessed.h -mlongint-impl=mpz $(MPY_FILES) > $@.tmp
	mv $@.tmp $@

$(CONTRACT_BUILD)/frozen_content.o: $(CONTRACT_BUILD)/frozen_content.c
	$(call compile_c)

$(CONTRACT_BUILD)/contract.raw.wasm: $(OBJ) $(SOFTFLOAT_LIB)
	$(CC) $^ $(LDFLAGS) -o $@

include $(TOP)/py/mkrules.mk
