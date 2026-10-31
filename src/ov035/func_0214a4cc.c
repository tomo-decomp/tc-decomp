// Overlay 35.
// Original: 0x0214A4CC
//   str r1, [r0, #0x70]   ; *(int *)(self + 0x70)  = value
//   str r1, [r0, #0x11c]  ; *(int *)(self + 0x11c) = value
//   bx  lr
void func_0214a4cc(char *self, int value);

void func_0214a4cc(char *self, int value)
{
    *(int *)(self + 0x70) = value;
    *(int *)(self + 0x11c) = value;
}
