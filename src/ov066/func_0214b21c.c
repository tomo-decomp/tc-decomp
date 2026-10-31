typedef unsigned char u8;
typedef short s16;

typedef struct {
    u8 pad_00[0x18];
    s16 unk_18;
    s16 unk_1a;
} Unk0214b21c;

void func_0214b21c(Unk0214b21c *self)
{
    self->unk_18 = self->unk_1a;
}
