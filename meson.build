project('tomo_coll_decomp',
    version: '0.1',
    meson_version: '>=1.12.0',
    default_options : [
        'buildtype=plain',
        'warning_level=0'
    ]
)

fs = import('fs')
python = import('python').find_installation('python3')


############################################################
###                    COMPILER FLAGS                    ###
############################################################
# These are the flags every decompiled function is built with. They mirror
# DEFAULT_FLAGS in tools/match.py, which is what actually proves a file
# compiles back to the original bytes today. meson/cross.ini drives the same
# CodeWarrior for ARM through wine (tools/mwcc.sh).
shared_args = [
    '-proc', 'arm946e',     # ARM9 (ARM946E-S)
    '-enum', 'int',
    '-lang', 'c99',
    '-Cpp_exceptions', 'off',
    '-gccext,on',
    '-gccinc',
    '-i', 'include',
    '-msgstyle', 'gcc',
    '-ipa', 'file',
    '-interworking',
    '-inline', 'on,noauto',
    '-char', 'signed',
    '-fp', 'soft',
    '-nosyspath',
    '-stdinc',
    '-sym', 'on',
    '-requireprotos',
    '-O4,p',                # optimize for speed
    '-D_MSL_RESTRICT=',
]

c_args = shared_args

mwcc_version = get_option('mwcc_version')


############################################################
###                     DEPENDENCIES                     ###
############################################################
# The game links against the NitroSDK, NitroSystem and libvct archives, the
# same way the other DS projects under dsdecomp/ do. The wraps in subprojects/
# pin the same revisions pokeplatinum and pokeheartgold use, so
#
#     meson subprojects download
#
# fetches them. They are not configured as dependencies yet: that needs the
# CodeWarrior/MSL standard library, which is not redistributable here, so the
# C compile and link targets land with the ROM-link milestone. Once the
# toolchain wrapper has the MSL include paths, these become:
#
#     sdk_dep = dependency('NitroSDK',
#         default_options: {'mwrap_sdk': mwcc_version, 'sp1p3_conditionals': true})
#     system_dep = dependency('NitroSystem',
#         default_options: {'mwrap_sdk': mwcc_version})
#     libvct_dep = dependency('libvct')


############################################################
###                        TOOLS                         ###
############################################################
subdir('tools')


############################################################
###                    DECOMPILED C                      ###
############################################################
subdir('src')


############################################################
###                     MATCH CHECK                      ###
############################################################
# `ninja check` runs the matching-decompilation harness over src/: every
# decompiled function must compile back to its original bytes.
check = custom_target('check',
    output: 'check.stamp',
    depend_files: tomo_coll_sources,
    command: [
        python, files('tools/match.py'), 'build',
        '--compiler', mwcc_version,
        '--stamp', '@OUTPUT@',
    ],
    build_by_default: false,
    console: true,
)

alias_target('check', check)
