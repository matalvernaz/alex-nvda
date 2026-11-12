// Keep Windows calls native while giving the downloaded Intel engine its Darwin calling convention.
#include <float.h>
#include <limits.h>
#include <signal.h>

// System declarations must be read before changing the convention of our guest entry points.
#undef __cdecl
#define __cdecl __attribute__((sysv_abi))

#define GUEST_VA_LIST __builtin_sysv_va_list
#define GUEST_VA_START(arguments, last) __builtin_sysv_va_start(arguments, last)
#define GUEST_VA_END(arguments) __builtin_sysv_va_end(arguments)
#define GUEST_VA_ARG(arguments, type) __builtin_va_arg(arguments, type)

extern void *modern_windows_cxx_symbol(const char *name);
extern int modern_windows_cxx_check(void);
