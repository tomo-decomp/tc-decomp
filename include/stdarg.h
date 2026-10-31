#ifndef TOMO_COLL_STDARG_H
#define TOMO_COLL_STDARG_H

/* Minimal stand-in for the Metrowerks MSL_C <stdarg.h>; see stddef.h. */
typedef char *va_list;

#define va_start(list, last) ((list) = (char *)&(last) + sizeof(last))
#define va_arg(list, type) (*(type *)(((list) += sizeof(type)), \
                                       (list) - sizeof(type)))
#define va_end(list) ((list) = (void *)0)

#endif
