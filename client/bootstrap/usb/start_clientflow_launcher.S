/*
 * ClientFlow USB root launcher for Ubuntu 26.04 / amd64.
 *
 * Design constraints:
 * - The USB medium is FAT32 and is mounted by UDisks with vfat showexec.
 * - The distributed filename is therefore "Start ClientFlow.EXE" so the
 *   kernel exposes execute permission on the removable FAT filesystem.
 * - This is a Linux ELF64 executable, not a Windows PE executable.
 * - There is deliberately no bootstrap, checksum, release-selection or sudo
 *   logic here. The only authority remains 01_START_CLIENTFLOW_USB.sh.
 * - No shell command string is constructed. The terminal and bash receive
 *   fixed argv vectors through execve(2). The launcher passes only the UX-only
 *   --hold-open flag so the canonical script keeps the terminal visible.
 * - The launcher is libc-free and uses only stable Linux x86-64 syscalls.
 *
 * Canonical regeneration command on Linux amd64 with GNU binutils:
 *   as --64 -o /tmp/start-clientflow.o client/bootstrap/usb/start_clientflow_launcher.S
 *   ld -m elf_x86_64 -nostdlib -static --build-id=none -z noexecstack \
 *      -e _start -o /tmp/Start\ ClientFlow.EXE /tmp/start-clientflow.o
 *   strip --strip-all /tmp/Start\ ClientFlow.EXE
 */

.section .text
.global _start
.type _start, @function
_start:
    /* Preserve envp for execve(). Stack: argc, argv..., NULL, envp... */
    mov (%rsp), %rax
    lea 16(%rsp,%rax,8), %r12

    /* Resolve our own path through /proc so Nautilus' cwd is irrelevant. */
    mov $89, %rax                  /* __NR_readlink */
    lea proc_self_exe(%rip), %rdi
    lea path_buffer(%rip), %rsi
    mov $4095, %rdx
    syscall
    test %rax, %rax
    jle fail_location

    lea path_buffer(%rip), %rsi
    movb $0, (%rsi,%rax,1)

    /* Strip the executable basename, leaving the USB root directory. */
    lea -1(%rsi,%rax,1), %rcx
find_slash:
    cmp %rsi, %rcx
    jb fail_location
    cmpb $'/', (%rcx)
    je found_slash
    dec %rcx
    jmp find_slash
found_slash:
    movb $0, (%rcx)

    /* Work from the USB root; the canonical shell script remains relative. */
    mov $80, %rax                  /* __NR_chdir */
    lea path_buffer(%rip), %rdi
    syscall
    test %rax, %rax
    jne fail_location

    /* Fail closed if the canonical entrypoint is not readable. */
    mov $21, %rax                  /* __NR_access */
    lea usb_script(%rip), %rdi
    mov $4, %rsi                   /* R_OK */
    syscall
    test %rax, %rax
    jne fail_script

    /* Ubuntu 26.04 default: Ptyxis. */
    lea ptyxis_path(%rip), %rdi
    lea ptyxis_argv(%rip), %rsi
    call try_exec

    /* Narrow compatibility fallbacks; all use fixed absolute executables. */
    lea x_terminal_path(%rip), %rdi
    lea x_terminal_argv(%rip), %rsi
    call try_exec

    lea gnome_terminal_path(%rip), %rdi
    lea gnome_terminal_argv(%rip), %rsi
    call try_exec

    lea kgx_path(%rip), %rdi
    lea kgx_argv(%rip), %rsi
    call try_exec

    lea xterm_path(%rip), %rdi
    lea xterm_argv(%rip), %rsi
    call try_exec

    lea terminal_error(%rip), %rsi
    mov $(terminal_error_end-terminal_error), %rdx
    mov $127, %rdi
    jmp write_error_and_exit

/*
 * try_exec(path, argv)
 * Returns only if path is not executable or execve fails.
 */
try_exec:
    push %rdi
    push %rsi
    mov $21, %rax                  /* __NR_access */
    mov $1, %rsi                   /* X_OK */
    syscall
    pop %rsi
    pop %rdi
    test %rax, %rax
    jne 1f

    mov $59, %rax                  /* __NR_execve */
    mov %r12, %rdx                 /* inherited envp */
    syscall
1:
    ret

fail_script:
    lea script_error(%rip), %rsi
    mov $(script_error_end-script_error), %rdx
    mov $66, %rdi
    jmp write_error_and_exit

fail_location:
    lea location_error(%rip), %rsi
    mov $(location_error_end-location_error), %rdx
    mov $70, %rdi

write_error_and_exit:
    /* rdi = exit status, rsi = message, rdx = length */
    mov %rdi, %r13
    mov $1, %rax                   /* __NR_write */
    mov $2, %rdi                   /* STDERR_FILENO */
    syscall
    mov $60, %rax                  /* __NR_exit */
    mov %r13, %rdi
    syscall

.section .rodata
proc_self_exe:
    .asciz "/proc/self/exe"
usb_script:
    .asciz "./01_START_CLIENTFLOW_USB.sh"
hold_open_arg:
    .asciz "--hold-open"
bash_path:
    .asciz "/usr/bin/bash"
title_arg:
    .asciz "--title=ClientFlow USB-klargøring"
title_flag:
    .asciz "--title"
title_value:
    .asciz "ClientFlow USB-klargøring"
separator_arg:
    .asciz "--"
xterm_title_flag:
    .asciz "-T"
xterm_exec_flag:
    .asciz "-e"

ptyxis_path:
    .asciz "/usr/bin/ptyxis"
x_terminal_path:
    .asciz "/usr/bin/x-terminal-emulator"
gnome_terminal_path:
    .asciz "/usr/bin/gnome-terminal"
kgx_path:
    .asciz "/usr/bin/kgx"
xterm_path:
    .asciz "/usr/bin/xterm"

location_error:
    .ascii "[FEJL] Start ClientFlow kunne ikke finde USB-mappen.\n"
location_error_end:
script_error:
    .ascii "[FEJL] 01_START_CLIENTFLOW_USB.sh mangler eller kan ikke læses.\n"
script_error_end:
terminal_error:
    .ascii "[FEJL] Ingen understøttet grafisk terminal blev fundet.\n"
terminal_error_end:

.section .data.rel.ro
.align 8
ptyxis_argv:
    .quad ptyxis_path, title_arg, separator_arg, bash_path, usb_script, hold_open_arg, 0
x_terminal_argv:
    .quad x_terminal_path, xterm_title_flag, title_value, xterm_exec_flag, bash_path, usb_script, hold_open_arg, 0
gnome_terminal_argv:
    .quad gnome_terminal_path, title_arg, separator_arg, bash_path, usb_script, hold_open_arg, 0
kgx_argv:
    .quad kgx_path, title_flag, title_value, separator_arg, bash_path, usb_script, hold_open_arg, 0
xterm_argv:
    .quad xterm_path, xterm_title_flag, title_value, xterm_exec_flag, bash_path, usb_script, hold_open_arg, 0

.section .bss
.align 16
path_buffer:
    .skip 4096

.section .note.GNU-stack,"",@progbits
