#include <stdint.h>
#include "softfloat.h"

// Inputs and outputs are IEEE bits in integers, never C floats. The Wasm
// rewriter changes all float types to the corresponding integer bit containers.
#define OPS(BITS, UINT, SIGN, INF, QNAN) \
static int nan##BITS(UINT a) { return (a & ~(SIGN)) > (INF); } \
UINT __sf_f##BITS##_abs(UINT a) { return a & ~(SIGN); } \
UINT __sf_f##BITS##_neg(UINT a) { return a ^ (SIGN); } \
UINT __sf_f##BITS##_copysign(UINT a, UINT b) { return (a & ~(SIGN)) | (b & (SIGN)); } \
UINT __sf_f##BITS##_add(UINT a, UINT b) { return f##BITS##_add((float##BITS##_t){a}, (float##BITS##_t){b}).v; } \
UINT __sf_f##BITS##_sub(UINT a, UINT b) { return f##BITS##_sub((float##BITS##_t){a}, (float##BITS##_t){b}).v; } \
UINT __sf_f##BITS##_mul(UINT a, UINT b) { return f##BITS##_mul((float##BITS##_t){a}, (float##BITS##_t){b}).v; } \
UINT __sf_f##BITS##_div(UINT a, UINT b) { return f##BITS##_div((float##BITS##_t){a}, (float##BITS##_t){b}).v; } \
UINT __sf_f##BITS##_sqrt(UINT a) { return f##BITS##_sqrt((float##BITS##_t){a}).v; } \
UINT __sf_f##BITS##_ceil(UINT a) { return f##BITS##_roundToInt((float##BITS##_t){a}, softfloat_round_max, false).v; } \
UINT __sf_f##BITS##_floor(UINT a) { return f##BITS##_roundToInt((float##BITS##_t){a}, softfloat_round_min, false).v; } \
UINT __sf_f##BITS##_trunc(UINT a) { return f##BITS##_roundToInt((float##BITS##_t){a}, softfloat_round_minMag, false).v; } \
UINT __sf_f##BITS##_nearest(UINT a) { return f##BITS##_roundToInt((float##BITS##_t){a}, softfloat_round_near_even, false).v; } \
uint32_t __sf_f##BITS##_eq(UINT a, UINT b) { return f##BITS##_eq((float##BITS##_t){a}, (float##BITS##_t){b}); } \
uint32_t __sf_f##BITS##_ne(UINT a, UINT b) { return !__sf_f##BITS##_eq(a, b); } \
uint32_t __sf_f##BITS##_lt(UINT a, UINT b) { return f##BITS##_lt_quiet((float##BITS##_t){a}, (float##BITS##_t){b}); } \
uint32_t __sf_f##BITS##_le(UINT a, UINT b) { return f##BITS##_le_quiet((float##BITS##_t){a}, (float##BITS##_t){b}); } \
uint32_t __sf_f##BITS##_gt(UINT a, UINT b) { return __sf_f##BITS##_lt(b, a); } \
uint32_t __sf_f##BITS##_ge(UINT a, UINT b) { return __sf_f##BITS##_le(b, a); } \
UINT __sf_f##BITS##_min(UINT a, UINT b) { \
  if (nan##BITS(a) || nan##BITS(b)) return QNAN; \
  if (((a | b) & ~(SIGN)) == 0) return a | b; \
  return __sf_f##BITS##_lt(a, b) ? a : b; \
} \
UINT __sf_f##BITS##_max(UINT a, UINT b) { \
  if (nan##BITS(a) || nan##BITS(b)) return QNAN; \
  if (((a | b) & ~(SIGN)) == 0) return a & b; \
  return __sf_f##BITS##_gt(a, b) ? a : b; \
}

OPS(32, uint32_t, UINT32_C(0x80000000), UINT32_C(0x7f800000), UINT32_C(0x7fc00000))
OPS(64, uint64_t, UINT64_C(0x8000000000000000), UINT64_C(0x7ff0000000000000), UINT64_C(0x7ff8000000000000))

#define CONVERT(FBITS, IBITS, SIGNEDNESS, CTYPE, PREFIX) \
CTYPE __sf_i##IBITS##_trunc_f##FBITS##_##SIGNEDNESS(uint##FBITS##_t a) { \
  softfloat_exceptionFlags = 0; \
  CTYPE result = f##FBITS##_to_##PREFIX##IBITS((float##FBITS##_t){a}, softfloat_round_minMag, false); \
  if (softfloat_exceptionFlags & softfloat_flag_invalid) __builtin_trap(); \
  return result; \
} \
uint##FBITS##_t __sf_f##FBITS##_convert_i##IBITS##_##SIGNEDNESS(CTYPE a) { \
  return PREFIX##IBITS##_to_f##FBITS(a).v; \
}

CONVERT(32, 32, s, int32_t, i)
CONVERT(32, 32, u, uint32_t, ui)
CONVERT(32, 64, s, int64_t, i)
CONVERT(32, 64, u, uint64_t, ui)
CONVERT(64, 32, s, int32_t, i)
CONVERT(64, 32, u, uint32_t, ui)
CONVERT(64, 64, s, int64_t, i)
CONVERT(64, 64, u, uint64_t, ui)

// Unlike LLVM's C-oriented lowering, these preserve Wasm's saturating
// conversion semantics for NaNs and values outside the destination range.
#define SAT_SIGNED(FBITS, IBITS) \
int##IBITS##_t __sf_i##IBITS##_trunc_sat_f##FBITS##_s(uint##FBITS##_t a) { \
  softfloat_exceptionFlags = 0; \
  int##IBITS##_t result = f##FBITS##_to_i##IBITS((float##FBITS##_t){a}, softfloat_round_minMag, false); \
  if (!(softfloat_exceptionFlags & softfloat_flag_invalid)) return result; \
  if (nan##FBITS(a)) return 0; \
  return (a >> (FBITS - 1)) ? INT##IBITS##_MIN : INT##IBITS##_MAX; \
}
#define SAT_UNSIGNED(FBITS, IBITS) \
uint##IBITS##_t __sf_i##IBITS##_trunc_sat_f##FBITS##_u(uint##FBITS##_t a) { \
  softfloat_exceptionFlags = 0; \
  uint##IBITS##_t result = f##FBITS##_to_ui##IBITS((float##FBITS##_t){a}, softfloat_round_minMag, false); \
  if (!(softfloat_exceptionFlags & softfloat_flag_invalid)) return result; \
  if (nan##FBITS(a) || (a >> (FBITS - 1))) return 0; \
  return UINT##IBITS##_MAX; \
}
SAT_SIGNED(32, 32)
SAT_SIGNED(32, 64)
SAT_SIGNED(64, 32)
SAT_SIGNED(64, 64)
SAT_UNSIGNED(32, 32)
SAT_UNSIGNED(32, 64)
SAT_UNSIGNED(64, 32)
SAT_UNSIGNED(64, 64)

uint32_t __sf_f32_demote_f64(uint64_t a) { return f64_to_f32((float64_t){a}).v; }
uint64_t __sf_f64_promote_f32(uint32_t a) { return f32_to_f64((float32_t){a}).v; }
