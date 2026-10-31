typedef unsigned char u8;

typedef struct {
    u8 pad_00[0x0c];
    int unk_0c;
    int unk_10;
} Unk0214ab8c;

void func_0214ab8c(Unk0214ab8c *self, int a, int b)
{
    self->unk_0c = a;
    self->unk_10 = b;
}
