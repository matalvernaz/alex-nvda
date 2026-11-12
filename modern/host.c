// Compile the modern 64-bit loader separately from the legacy NVDA host.
#define TIGER_GUEST_64
#define TIGER_AAC_GLINT
#include "../vendor/panthera/src/tiger_host.c"
