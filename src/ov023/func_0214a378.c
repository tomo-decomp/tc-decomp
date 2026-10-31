// Overlay 23.
// Original: 0x0214A378
//   stm  r0, {r2, r3}   ; field_00 = arg2, field_04 = arg3
//   str  r1, [r0, #0x10]; field_10 = arg1
//   bx   lr
typedef struct {
    int field_00;
    int field_04;
    int field_08;
    int field_0c;
    int field_10;
} struct_0214a378;

void func_0214a378(struct_0214a378 *self, int a, int b, int c);

void func_0214a378(struct_0214a378 *self, int a, int b, int c)
{
    self->field_00 = b;
    self->field_04 = c;
    self->field_10 = a;
}
