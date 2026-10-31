// Overlay 65.
// Original: 0x0214B4BC
//   str r1, [r0]      ; self->field_00 = value
//   mov r1, #0
//   str r1, [r0, #4]  ; self->field_04 = 0
//   str r1, [r0, #8]  ; self->field_08 = 0
//   bx  lr
typedef struct {
    int field_00;
    int field_04;
    int field_08;
} struct_0214b4bc;

void func_0214b4bc(struct_0214b4bc *self, int value);

void func_0214b4bc(struct_0214b4bc *self, int value)
{
    self->field_00 = value;
    self->field_04 = 0;
    self->field_08 = 0;
}
