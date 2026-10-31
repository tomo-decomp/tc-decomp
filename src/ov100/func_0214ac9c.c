typedef unsigned char u8;
typedef unsigned short u16;

typedef struct {
    u8 pad_00[0x04];
    u16 unk_04;
    u8 pad_06[0x2c - 0x06];
    int unk_2c;
    int unk_30;
} Unk0214ac9c;

void func_0214ac9c(Unk0214ac9c *self, int mode, int value)
{
    self->unk_2c = mode;
    switch (mode) {
    case 0:
        self->unk_04 = value;
        self->unk_30 = value;
        break;
    case 1:
        self->unk_04 = value;
        self->unk_30 = 0xf7;
        break;
    case 2:
        self->unk_04 = value;
        self->unk_30 = 0xf9;
        break;
    case 3:
        self->unk_04 = value;
        self->unk_30 = 0xf4;
        break;
    case 4:
        self->unk_04 = value;
        self->unk_30 = 0xf5;
        break;
    }
}
