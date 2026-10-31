#ifndef TOMO_COLL_STDDEF_H
#define TOMO_COLL_STDDEF_H

/* Minimal stand-in for the Metrowerks MSL_C <stddef.h>. The MSL_C headers
   are not part of this repository (they ship with the licensed CodeWarrior /
   NitroSDK install), so the handful of declarations the decompiled code and
   the compiler driver need are provided here. */

typedef unsigned int size_t;
typedef int ptrdiff_t;
typedef unsigned short wchar_t;

#define NULL ((void *)0)
#define offsetof(type, member) ((size_t) & (((type *)0)->member))

#endif
