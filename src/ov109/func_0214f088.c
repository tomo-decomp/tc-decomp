typedef unsigned char u8;
typedef short s16;

typedef struct {
    u8 pad_00[0x1e];
    s16 unk_1e;
} Unk020fb870;

extern Unk020fb870 data_020fb870;

s16 func_0214f088(void)
{
    return data_020fb870.unk_1e;
}
