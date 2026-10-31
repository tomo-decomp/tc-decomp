typedef unsigned char u8;

typedef struct {
    u8 pad_00[0x04];
    int unk_04;
} Unk0214b5f0;

extern int data_0214ea28[];

int func_0214b5f0(Unk0214b5f0 *self)
{
    return data_0214ea28[self->unk_04];
}
