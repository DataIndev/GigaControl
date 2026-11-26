#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#ifndef APP_VERSION
#define APP_VERSION "1.0.0"
#endif

static int file_readable(const char *path) {
    return path && access(path, R_OK) == 0;
}

static int build_path2(char *dst, size_t dst_sz, const char *a, const char *b) {
    size_t la = strlen(a);
    size_t lb = strlen(b);
    if (la + 1 + lb + 1 > dst_sz) {
        return -1;
    }
    memcpy(dst, a, la);
    dst[la] = '/';
    memcpy(dst + la + 1, b, lb);
    dst[la + 1 + lb] = '\0';
    return 0;
}

static int try_candidate(const char *dir, char *out_pyz, size_t out_sz, char *out_dir, size_t dir_sz) {
    char cand[PATH_MAX];
    if (build_path2(cand, sizeof(cand), dir, "gigabyte-control-center.pyz") != 0) {
        return -1;
    }
    if (!file_readable(cand)) {
        return -1;
    }
    if (strlen(cand) + 1 > out_sz || strlen(dir) + 1 > dir_sz) {
        return -1;
    }
    strcpy(out_pyz, cand);
    strcpy(out_dir, dir);
    return 0;
}

static int find_pyz(char *out_pyz, size_t out_sz, char *out_dir, size_t dir_sz) {
    char exe_path[PATH_MAX];
    ssize_t len = readlink("/proc/self/exe", exe_path, sizeof(exe_path) - 1);
    char exe_dir[PATH_MAX] = ".";
    if (len > 0) {
        exe_path[len] = '\0';
        char *d = dirname(exe_path);
        if (strlen(d) < sizeof(exe_dir)) {
            strcpy(exe_dir, d);
        }
    }

    if (try_candidate(exe_dir, out_pyz, out_sz, out_dir, dir_sz) == 0) {
        return 0;
    }

    const char *home = getenv("HOME");
    if (home && home[0] != '\0') {
        char dir2[PATH_MAX];
        if (build_path2(dir2, sizeof(dir2), home, ".local/share/gigabyte-control-center") == 0) {
            if (try_candidate(dir2, out_pyz, out_sz, out_dir, dir_sz) == 0) {
                return 0;
            }
        }
    }

    char dir3[PATH_MAX];
    if (build_path2(dir3, sizeof(dir3), exe_dir, "../share/gigabyte-control-center") == 0) {
        if (try_candidate(dir3, out_pyz, out_sz, out_dir, dir_sz) == 0) {
            return 0;
        }
    }

    return -1;
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        printf("GigaControl Center %s\n", APP_VERSION);
        return 0;
    }

    char pyz_path[PATH_MAX];
    char data_dir[PATH_MAX];
    if (find_pyz(pyz_path, sizeof(pyz_path), data_dir, sizeof(data_dir)) != 0) {
        fprintf(stderr,
                "Error: no se encontró 'gigabyte-control-center.pyz'.\n"
                "Ejecuta 'make && make install-user' en el directorio del proyecto.\n");
        return 1;
    }

    setenv("GIGACC_DATA_DIR", data_dir, 1);

    char **py_argv = calloc((size_t)argc + 2, sizeof(char *));
    if (!py_argv) {
        perror("calloc");
        return 1;
    }

    py_argv[0] = "/usr/bin/python3";
    py_argv[1] = pyz_path;
    for (int i = 1; i < argc; ++i) {
        py_argv[i + 1] = argv[i];
    }
    py_argv[argc + 1] = NULL;

    execv("/usr/bin/python3", py_argv);
    fprintf(stderr, "Error al iniciar /usr/bin/python3 (%s): %s\n", pyz_path, strerror(errno));
    free(py_argv);
    return 1;
}
