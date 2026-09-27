/*
 * JARVIS.app CFBundleExecutable — embeds CPython and runs Resources/boot.py
 * in-process so Dock / Cmd-Tab / menu bar show "JARVIS" (not "Python").
 */
#include <Python.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <mach-o/dyld.h>

static void die(const char *msg) {
    fprintf(stderr, "JARVIS launcher: %s\n", msg);
    exit(1);
}

int main(int argc, char **argv) {
    char exe[PATH_MAX];
    uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0)
        die("cannot resolve executable path");

    char resolved[PATH_MAX];
    if (!realpath(exe, resolved)) {
        strncpy(resolved, exe, sizeof(resolved) - 1);
        resolved[sizeof(resolved) - 1] = '\0';
    }

    char macos_dir[PATH_MAX];
    strncpy(macos_dir, resolved, sizeof(macos_dir) - 1);
    macos_dir[sizeof(macos_dir) - 1] = '\0';
    char *slash = strrchr(macos_dir, '/');
    if (!slash)
        die("bad executable path");
    *slash = '\0';

    char boot_rel[PATH_MAX];
    char boot_path[PATH_MAX];
    snprintf(boot_rel, sizeof(boot_rel), "%s/../Resources/boot.py", macos_dir);
    if (!realpath(boot_rel, boot_path))
        die("missing Resources/boot.py");

    const char *repo = "/Users/jonaskroeger/JARVIS";
    (void)chdir(repo);

    PyStatus status;
    PyConfig config;
    PyConfig_InitPythonConfig(&config);
    config.buffered_stdio = 0;
    config.parse_argv = 0;

    status = PyConfig_SetBytesString(&config, &config.program_name, resolved);
    if (PyStatus_Exception(status)) {
        PyConfig_Clear(&config);
        Py_ExitStatusException(status);
    }

    /* Python argv: [program, boot.py, ...user args] */
    int py_argc = argc + 1;
    char **py_argv = calloc((size_t)py_argc, sizeof(char *));
    if (!py_argv)
        die("out of memory");
    py_argv[0] = resolved;
    py_argv[1] = boot_path;
    for (int i = 1; i < argc; i++)
        py_argv[i + 1] = argv[i];

    status = PyConfig_SetBytesArgv(&config, py_argc, py_argv);
    if (PyStatus_Exception(status)) {
        free(py_argv);
        PyConfig_Clear(&config);
        Py_ExitStatusException(status);
    }

    status = Py_InitializeFromConfig(&config);
    PyConfig_Clear(&config);
    if (PyStatus_Exception(status)) {
        free(py_argv);
        Py_ExitStatusException(status);
    }

    FILE *fp = fopen(boot_path, "rb");
    if (!fp) {
        free(py_argv);
        Py_Finalize();
        die("cannot open Resources/boot.py");
    }
    int rc = PyRun_SimpleFileExFlags(fp, boot_path, 1, NULL);
    if (Py_FinalizeEx() < 0)
        rc = 120;
    free(py_argv);
    return (rc == 0) ? 0 : 1;
}
