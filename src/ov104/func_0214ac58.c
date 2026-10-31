typedef unsigned char u8;

typedef struct {
    u8 pad_00[0x0c];
    int unk_0c;
    int unk_10;
} Unk0214ac58;

void func_0214ac58(Unk0214ac58 *self, int a, int b)
{
    self->unk_0c = a;
    self->unk_10 = b;
}
