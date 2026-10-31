typedef unsigned char u8;
typedef unsigned short u16;
typedef signed int s32;

typedef struct {
    s32 x;
    s32 y;
    s32 z;
} Vec3;

/* The object at self->unk_08. Only the regions this function touches are
   modeled; the real extent is unknown. It is a distinct type from the one
   holding self so the compiler can tell the two cannot alias. */
typedef struct {
    u8 pad_000[0x6c4];
    Vec3 unk_6c4;
} Unk2000;

struct Unk0200;
typedef struct Unk0200 Unk0200;

typedef struct {
    u8 pad_00[0x8a];
    u16 unk_8a;
} Unk2600;

typedef struct {
    u8 pad_00[0x48];
    u8 unk_48[0x24];
    u8 unk_6c[0x94];
} Unk26f8;

typedef struct {
    u8 pad_00[0x24];
    Vec3 unk_24;
    u8 pad_30[0x54];
    Vec3 unk_84;
    u8 pad_90[0x24];
    Vec3 unk_b4;
} Unk2860;

typedef struct {
    s32 unk_00;
    u8 pad_04[0x04];
    Unk0200 *unk_08;
    u8 pad_0c[0x68];
    u8 unk_74[0x30];
    Vec3 unk_a4;
    u16 unk_b0;
    u16 unk_b2;
    u16 unk_b4;
} Unk0214b978;

extern void func_02009978(void *a, void *b);

#define SUBSYS(p) ((Unk26f8 *)((u8 *)(p) + 0x26f8))

void func_0214b978(Unk0214b978 *self)
{
    Unk2860 *vecs;
    s32 x, y, z;

    switch (self->unk_00) {
    case 1:
    case 4:
        vecs = (Unk2860 *)((u8 *)self->unk_08 + 0x2860);
        z = vecs->unk_b4.z;
        y = vecs->unk_b4.y;
        x = vecs->unk_b4.x;
        self->unk_a4.x = x;
        self->unk_a4.y = y;
        self->unk_a4.z = z;
        func_02009978(SUBSYS(self->unk_08)->unk_6c, self->unk_74);
        self->unk_b4 = 0x4000;
        break;
    case 2:
    case 3:
        vecs = (Unk2860 *)((u8 *)self->unk_08 + 0x2860);
        z = vecs->unk_24.z;
        y = vecs->unk_24.y;
        x = vecs->unk_24.x;
        self->unk_a4.x = x;
        self->unk_a4.y = y;
        self->unk_a4.z = z;
        func_02009978(SUBSYS(self->unk_08), self->unk_74);
        self->unk_b4 = 0xc000;
        break;
    case 5:
        vecs = (Unk2860 *)((u8 *)self->unk_08 + 0x2860);
        z = vecs->unk_84.z;
        y = vecs->unk_84.y;
        x = vecs->unk_84.x;
        self->unk_a4.x = x;
        self->unk_a4.y = y;
        self->unk_a4.z = z;
        func_02009978(SUBSYS(self->unk_08)->unk_48, self->unk_74);
        self->unk_b0 = 0x11c7;
        self->unk_b2 = 0x2aaa;
        self->unk_b4 = 0xdc72;
        break;
    case 7:
        z = ((Unk2000 *)((u8 *)self->unk_08 + 0x2000))->unk_6c4.z;
        y = ((Unk2000 *)((u8 *)self->unk_08 + 0x2000))->unk_6c4.y;
        x = ((Unk2000 *)((u8 *)self->unk_08 + 0x2000))->unk_6c4.x;
        self->unk_a4.x = x;
        self->unk_a4.y = y;
        self->unk_a4.z = z;
        self->unk_b2 = ((Unk2600 *)((u8 *)self->unk_08 + 0x2600))->unk_8a;
        break;
    }
}
