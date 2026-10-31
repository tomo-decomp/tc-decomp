// Overlay 45.
// Original: 0x0214AC30
//   str r1, [r0, #0x84]   ; *(int *)(self + 0x84)  = value
//   str r1, [r0, #0x130]  ; *(int *)(self + 0x130) = value
//   bx  lr
void func_0214ac30(char *self, int value);

void func_0214ac30(char *self, int value)
{
    *(int *)(self + 0x84) = value;
    *(int *)(self + 0x130) = value;
}
