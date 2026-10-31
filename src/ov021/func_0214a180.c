// Overlay 21.
// Original: 0x0214A180
//   add r0, r0, #0x5000
//   mov r2, #0
//   str r2, [r0, #0x20]  ; *(int *)(self + 0x5020) = 0
//   str r1, [r0, #0x1c]  ; *(int *)(self + 0x501c) = value
//   bx  lr
void func_0214a180(char *self, int value);

void func_0214a180(char *self, int value)
{
    *(int *)(self + 0x5000 + 0x20) = 0;
    *(int *)(self + 0x5000 + 0x1c) = value;
}
