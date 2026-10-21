include $(TOP)/py/mkenv.mk
QSTR_DEFS = qstrdefsport.h
include $(TOP)/py/py.mk

INC += -I. -I$(TOP) -I$(BUILD) -I$(GENERATED)
CFLAGS += $(INC) -std=c99 -Oz -flto -DNDEBUG -fwrapv -fno-jump-tables
CFLAGS += -mno-bulk-memory -mno-reference-types -mno-multivalue
CFLAGS += -mno-nontrapping-fptoint -mno-sign-ext -mno-simd128 -mno-atomics
LDFLAGS += -Oz -flto --no-entry -sSTANDALONE_WASM=1 -sFILESYSTEM=0
LDFLAGS += -sSUPPORT_LONGJMP=0 -sINITIAL_MEMORY=4194304 -sSTACK_SIZE=262144
LDFLAGS += -sALLOW_MEMORY_GROWTH=0 -sMALLOC=emmalloc
SRC_C = adapter.c system.c
ifneq ($(SOFTFLOAT_LIB),)
SRC_C += softfloat/ops.c
CFLAGS += $(SOFTFLOAT_FLAGS)
LDFLAGS += $(SOFTFLOAT_EXPORTS)
endif
SRC_QSTR += adapter.c
OBJ += $(PY_CORE_O) $(addprefix $(BUILD)/,$(SRC_C:.c=.o)) $(BUILD)/entrypoints.o $(BUILD)/frozen_content.o
MPY_FILES = $(wildcard $(GENERATED)/*.mpy)

all: $(BUILD)/contract.raw.wasm

$(BUILD)/entrypoints.o: $(GENERATED)/entrypoints.c
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/frozen_content.c: $(MPY_FILES) $(BUILD)/genhdr/qstrdefs.generated.h
	$(PYTHON) $(TOP)/tools/mpy-tool.py -f -q $(BUILD)/genhdr/qstrdefs.preprocessed.h -mlongint-impl=mpz $(MPY_FILES) > $@.tmp
	mv $@.tmp $@

$(BUILD)/contract.raw.wasm: $(OBJ) $(SOFTFLOAT_LIB)
	$(CC) $^ $(LDFLAGS) -o $@

include $(TOP)/py/mkrules.mk
