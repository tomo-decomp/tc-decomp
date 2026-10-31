// Overlay 42.
// Original: 0x0214ACA8
//   str r1, [r0, #0x64]   ; *(int *)(self + 0x64)  = value
//   str r1, [r0, #0x110]  ; *(int *)(self + 0x110) = value
//   bx  lr
void func_0214aca8(char *self, int value);

void func_0214aca8(char *self, int value)
{
    *(int *)(self + 0x64) = value;
    *(int *)(self + 0x110) = value;
}
