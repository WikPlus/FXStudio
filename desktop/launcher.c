// Launch the bundled Electron executable with English native macOS controls.
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char location[PATH_MAX], canonical[PATH_MAX], executable[PATH_MAX];
    uint32_t length = sizeof(location);
    if (_NSGetExecutablePath(location, &length) != 0 || !realpath(location, canonical)) {
        perror("FX Studio could not locate its runtime");
        return 1;
    }
    char *slash = strrchr(canonical, '/');
    if (!slash) return 1;
    *slash = '\0';
    int written = snprintf(executable, sizeof(executable), "%s/Electron", canonical);
    if (written < 0 || (size_t)written >= sizeof(executable)) return 1;
    char **arguments = calloc((size_t)argc + 5, sizeof(char *));
    if (!arguments) return 1;
    arguments[0] = executable;
    arguments[1] = "-AppleLanguages";
    arguments[2] = "(en)";
    arguments[3] = "-AppleLocale";
    arguments[4] = "en_US";
    for (int i = 1; i < argc; i++) arguments[i + 4] = argv[i];
    unsetenv("ELECTRON_RUN_AS_NODE");
    execv(executable, arguments);
    perror("FX Studio could not start Electron");
    free(arguments);
    return 1;
}
