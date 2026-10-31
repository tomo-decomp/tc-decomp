typedef unsigned char u8;

typedef struct {
    u8 pad_00[0x04];
    int unk_04;
} Unk0214b3e0;

extern int data_0214ea08[];

int func_0214b3e0(Unk0214b3e0 *self)
{
    return data_0214ea08[self->unk_04];
}
