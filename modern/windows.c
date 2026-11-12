// Translate the Darwin x64 calls that cross into Windows' C runtime and system ICU.
#define WINDOWS_WRAPPER(result, name, parameters, arguments) \
	static result __cdecl windows_##name parameters { return name arguments; }

WINDOWS_WRAPPER(void *, memset, (void *memory, int value, size_t size), (memory, value, size))
WINDOWS_WRAPPER(void *, memchr, (const void *memory, int value, size_t size), (memory, value, size))
WINDOWS_WRAPPER(int, memcmp, (const void *left, const void *right, size_t size), (left, right, size))
WINDOWS_WRAPPER(int, strcmp, (const char *left, const char *right), (left, right))
WINDOWS_WRAPPER(int, _stricmp, (const char *left, const char *right), (left, right))
WINDOWS_WRAPPER(int, _strnicmp, (const char *left, const char *right, size_t size), (left, right, size))
WINDOWS_WRAPPER(char *, strchr, (const char *text, int character), (text, character))
WINDOWS_WRAPPER(char *, strstr, (const char *text, const char *part), (text, part))
WINDOWS_WRAPPER(char *, strpbrk, (const char *text, const char *set), (text, set))
WINDOWS_WRAPPER(char *, strcpy, (char *output, const char *text), (output, text))
WINDOWS_WRAPPER(size_t, strlen, (const char *text), (text))
WINDOWS_WRAPPER(char *, getenv, (const char *name), (name))
WINDOWS_WRAPPER(int, atoi, (const char *text), (text))
WINDOWS_WRAPPER(double, atof, (const char *text), (text))
static int64_t __cdecl windows_atol(const char *text) { return _strtoi64(text, NULL, 10); }
static void __cdecl windows_free(void *memory) { free(memory); }
WINDOWS_WRAPPER(void *, calloc, (size_t count, size_t size), (count, size))

#define WINDOWS_MATH(name) WINDOWS_WRAPPER(double, name, (double value), (value))
#define WINDOWS_MATH_FLOAT(name) WINDOWS_WRAPPER(float, name, (float value), (value))
WINDOWS_MATH(ceil)
WINDOWS_MATH(floor)
WINDOWS_MATH(cos)
WINDOWS_MATH(sin)
WINDOWS_MATH(sqrt)
WINDOWS_MATH(log)
WINDOWS_MATH(log10)
WINDOWS_MATH(sinh)
WINDOWS_MATH_FLOAT(ceilf)
WINDOWS_MATH_FLOAT(floorf)
WINDOWS_MATH_FLOAT(expf)
WINDOWS_MATH_FLOAT(logf)
WINDOWS_MATH_FLOAT(sinhf)
WINDOWS_MATH_FLOAT(cosf)
WINDOWS_MATH_FLOAT(sinf)
WINDOWS_WRAPPER(double, pow, (double base, double exponent), (base, exponent))
WINDOWS_WRAPPER(float, powf, (float base, float exponent), (base, exponent))

static void *windows_icu_function(const char *name) {
	static HMODULE library;
	static int external;
	static __thread int initialized;
	if (!initialized) {
		HRESULT result = CoInitializeEx(NULL, COINIT_MULTITHREADED);
		if (FAILED(result) && result != RPC_E_CHANGED_MODE) { die("cannot initialize Windows Unicode services"); }
		initialized = 1;
	}
	if (!library) {
		// An override permits local Wine comparison tests. Released Windows uses its own ICU, never a network download.
		const char *override = getenv("ALEX_TEST_ICU_LIBRARY");
		external = override && *override;
		library = external ? LoadLibraryA(override) : LoadLibraryW(L"icu.dll");
	}
	if (!library) { die("Windows ICU is unavailable. Install current Windows updates and retry Alex setup."); }
	void *function = (void *)GetProcAddress(library, name);
	if (!function && external) {
		char versioned[128];
		snprintf(versioned, sizeof(versioned), "%s_76", name);
		function = (void *)GetProcAddress(library, versioned);
	}
	if (!function) { die("Windows ICU lacks %s. Install current Windows updates and retry Alex setup.", name); }
	return function;
}

typedef struct {
	const void *context;
	int32_t length, start, index, limit, reserved;
	void *functions[10];
} windows_iterator;
static void *windows_iterator_functions[10];

static int32_t __cdecl iterator_index(windows_iterator *iterator, int origin) {
	typedef int32_t (*function_type)(void *, int);
	return ((function_type)windows_iterator_functions[0])(iterator, origin);
}
static int32_t __cdecl iterator_move(windows_iterator *iterator, int32_t amount, int origin) {
	typedef int32_t (*function_type)(void *, int32_t, int);
	return ((function_type)windows_iterator_functions[1])(iterator, amount, origin);
}
#define ITERATOR_CALL(name, index, result) \
	static result __cdecl iterator_##name(windows_iterator *iterator) { \
		typedef result (*function_type)(void *); \
		return ((function_type)windows_iterator_functions[index])(iterator); \
	}
ITERATOR_CALL(has_next, 2, int8_t)
ITERATOR_CALL(has_previous, 3, int8_t)
ITERATOR_CALL(current, 4, int32_t)
ITERATOR_CALL(next, 5, int32_t)
ITERATOR_CALL(previous, 6, int32_t)
ITERATOR_CALL(state, 8, uint32_t)
static void __cdecl iterator_set_state(windows_iterator *iterator, uint32_t state, int32_t *error) {
	typedef void (*function_type)(void *, uint32_t, int32_t *);
	((function_type)windows_iterator_functions[9])(iterator, state, error);
}
static void *windows_iterator_adapters[10] = {
	(void *)iterator_index, (void *)iterator_move, (void *)iterator_has_next, (void *)iterator_has_previous,
	(void *)iterator_current, (void *)iterator_next, (void *)iterator_previous, NULL, (void *)iterator_state, (void *)iterator_set_state
};

static void __cdecl windows_uiter_setString(windows_iterator *iterator, const uint16_t *text, int32_t length) {
	typedef void (*function_type)(void *, const uint16_t *, int32_t);
	((function_type)windows_icu_function("uiter_setString"))(iterator, text, length);
	for (unsigned index = 0; index < 10; index++) {
		windows_iterator_functions[index] = iterator->functions[index];
		if (iterator->functions[index]) { iterator->functions[index] = windows_iterator_adapters[index]; }
	}
}

static const void *windows_normalizer(int mode, int32_t options, int32_t *error) {
	static const void *filtered[7];
	const char *getter;
	switch (mode) {
		case 1: return NULL;
		case 2: getter = "unorm2_getNFDInstance"; break;
		case 3: getter = "unorm2_getNFKDInstance"; break;
		case 4: getter = "unorm2_getNFCInstance"; break;
		case 5: getter = "unorm2_getNFKCInstance"; break;
		case 6: getter = NULL; break;
		default: *error = 1; return NULL;
	}
	const void *normalizer;
	if (getter) {
		typedef const void *(*function_type)(int32_t *);
		normalizer = ((function_type)windows_icu_function(getter))(error);
	}
	else {
		typedef const void *(*function_type)(const char *, const char *, int, int32_t *);
		normalizer = ((function_type)windows_icu_function("unorm2_getInstance"))(NULL, "nfc", 2, error);
	}
	if (*error > 0 || !(options & 0x20)) { return normalizer; }
	if (!filtered[mode]) {
		typedef void *(*set_type)(const uint16_t *, int32_t, int32_t *);
		typedef const void *(*filter_type)(const void *, const void *, int32_t *);
		// The filter and its normalizer live together for this isolated host's lifetime.
		void *set = ((set_type)windows_icu_function("uset_openPattern"))((const uint16_t *)L"[:age=3.2:]", -1, error);
		if (*error <= 0) { filtered[mode] = ((filter_type)windows_icu_function("unorm2_openFiltered"))(normalizer, set, error); }
	}
	return filtered[mode];
}

static int32_t __cdecl windows_unorm_next(void *value, uint16_t *output, int32_t capacity, int mode, int32_t options, int8_t normalize, int8_t *needed, int32_t *error) {
	// Windows omits deprecated unorm_next. Implement its iterator contract with supported Normalizer2 APIs.
	if (!error || *error > 0) { return 0; }
	windows_iterator *iterator = value;
	if (!iterator || capacity < 0 || (!output && capacity) || iterator->index < iterator->start || iterator->index > iterator->limit || iterator->limit > MODERN_MAXIMUM_TEXT_UNITS || (!iterator->context && iterator->limit)) {
		*error = 1;
		return 0;
	}
	const void *normalizer = windows_normalizer(mode, options, error);
	if (*error > 0) { return 0; }
	typedef int8_t (*boundary_type)(const void *, int32_t);
	boundary_type boundary = normalizer ? (boundary_type)windows_icu_function("unorm2_hasBoundaryBefore") : NULL;
	const uint16_t empty[1] = { 0 };
	const uint16_t *text = iterator->context ? iterator->context : empty;
	int32_t start = iterator->index, end = start;
	while (end < iterator->limit) {
		int32_t character = text[end], width = 1;
		if (character >= 0xd800 && character <= 0xdbff && end + 1 < iterator->limit && text[end + 1] >= 0xdc00 && text[end + 1] <= 0xdfff) {
			character = 0x10000 + ((character - 0xd800) << 10) + text[end + 1] - 0xdc00;
			width = 2;
		}
		if (end != start && (!boundary || boundary(normalizer, character))) { break; }
		end += width;
	}
	iterator->index = end;
	if (needed) { *needed = 0; }
	int32_t length = end - start;
	if (normalize && normalizer) {
		typedef int32_t (*function_type)(const void *, const uint16_t *, int32_t, uint16_t *, int32_t, int32_t *);
		int32_t result = ((function_type)windows_icu_function("unorm2_normalize"))(normalizer, text + start, length, output, capacity, error);
		if (needed && *error <= 0) { *needed = result != length || (length && memcmp(output, text + start, length * 2) != 0); }
		return result;
	}
	if (capacity) { memcpy(output, text + start, (length < capacity ? length : capacity) * 2); }
	if (length < capacity) { output[length] = 0; }
	else { *error = length > capacity ? 15 : -124; }
	return length;
}

static int32_t __cdecl windows_u_charName(int32_t character, int choice, char *output, int32_t capacity, int32_t *error) {
	typedef int32_t (*function_type)(int32_t, int, char *, int32_t, int32_t *);
	return ((function_type)windows_icu_function("u_charName"))(character, choice, output, capacity, error);
}

static int8_t __cdecl windows_u_isgraph(int32_t character) {
	typedef int8_t (*function_type)(int32_t);
	return ((function_type)windows_icu_function("u_isgraph"))(character);
}

static int __cdecl windows_sqlite_open_v2(const char *path, void **database, int flags, const char *vfs) {
	typedef int (*function_type)(const char *, void **, int, const char *);
	HMODULE library = LoadLibraryW(L"winsqlite3.dll");
	function_type function = library ? (function_type)GetProcAddress(library, "sqlite3_open_v2") : NULL;
	if (!function) { die("Windows SQLite is unavailable. Install current Windows updates and retry Alex setup."); }
	return function(path, database, flags, vfs);
}

static const void *__cdecl windows_sqlite_column_blob(void *statement, int column) {
	typedef const void *(*function_type)(void *, int);
	HMODULE library = LoadLibraryW(L"winsqlite3.dll");
	function_type function = library ? (function_type)GetProcAddress(library, "sqlite3_column_blob") : NULL;
	if (!function) { die("Windows SQLite lacks sqlite3_column_blob"); }
	return function(statement, column);
}

static int __cdecl windows_sqlite_column_bytes(void *statement, int column) {
	typedef int (*function_type)(void *, int);
	HMODULE library = LoadLibraryW(L"winsqlite3.dll");
	function_type function = library ? (function_type)GetProcAddress(library, "sqlite3_column_bytes") : NULL;
	if (!function) { die("Windows SQLite lacks sqlite3_column_bytes"); }
	return function(statement, column);
}

static void *modern_windows_symbol(const char *name) {
	static const struct { const char *name; void *function; } functions[] = {
#define WINDOWS_BIND(name) { "_" #name, (void *)windows_##name }
		WINDOWS_BIND(memset), WINDOWS_BIND(memchr), WINDOWS_BIND(memcmp), WINDOWS_BIND(strcmp),
		{ "_strcasecmp", (void *)windows__stricmp }, { "_strncasecmp", (void *)windows__strnicmp },
		WINDOWS_BIND(strchr), WINDOWS_BIND(strstr), WINDOWS_BIND(strpbrk), WINDOWS_BIND(strcpy), WINDOWS_BIND(strlen),
		WINDOWS_BIND(getenv), WINDOWS_BIND(atoi), WINDOWS_BIND(atof), WINDOWS_BIND(atol), WINDOWS_BIND(free), WINDOWS_BIND(calloc),
		WINDOWS_BIND(ceil), WINDOWS_BIND(floor), WINDOWS_BIND(cos), WINDOWS_BIND(sin), WINDOWS_BIND(sqrt), WINDOWS_BIND(log), WINDOWS_BIND(log10), WINDOWS_BIND(sinh), WINDOWS_BIND(pow),
		WINDOWS_BIND(ceilf), WINDOWS_BIND(floorf), WINDOWS_BIND(cosf), WINDOWS_BIND(sinf), WINDOWS_BIND(expf), WINDOWS_BIND(logf), WINDOWS_BIND(sinhf), WINDOWS_BIND(powf),
		WINDOWS_BIND(uiter_setString), WINDOWS_BIND(unorm_next), WINDOWS_BIND(u_charName), WINDOWS_BIND(u_isgraph),
		{ "_sqlite3_open_v2", (void *)windows_sqlite_open_v2 },
		{ "_sqlite3_column_blob", (void *)windows_sqlite_column_blob }, { "_sqlite3_column_bytes", (void *)windows_sqlite_column_bytes },
	};
	for (unsigned index = 0; index < sizeof(functions) / sizeof(functions[0]); index++) {
		if (!strcmp(name, functions[index].name)) { return functions[index].function; }
	}
	return modern_windows_cxx_symbol(name);
}

static int modern_windows_runtime_check(void) {
	if (modern_windows_cxx_check()) { die("the bundled C++ runtime has an incompatible string layout"); }
	const uint16_t text[] = { 'c', 'a', 'f', 0xe9 };
	windows_iterator iterator;
	windows_uiter_setString(&iterator, text, 4);
	if (iterator_next(&iterator) != 'c' || iterator.index != 1) { die("the Windows Unicode iterator ABI check failed"); }
	uint16_t output[16];
	int32_t error = 0;
	int8_t needed;
	if (windows_unorm_next(&iterator, output, 16, 2, 0, 1, &needed, &error) < 1 || error > 0 || output[0] != 'a') { die("the Windows Unicode normalization check failed"); }
	const uint16_t accent[] = { 0xe9, 'x' }, combining[] = { 'e', 0x301, 'x' }, emoji[] = { 0xd83d, 0xde00, 'x' };
	error = 0;
	windows_uiter_setString(&iterator, accent, 2);
	if (windows_unorm_next(&iterator, output, 16, 2, 0, 1, &needed, &error) != 2 || error > 0 || output[0] != 'e' || output[1] != 0x301 || iterator.index != 1 || !needed) { die("the Windows Unicode decomposition check failed"); }
	error = 0;
	windows_uiter_setString(&iterator, combining, 3);
	if (windows_unorm_next(&iterator, output, 16, 4, 0, 1, &needed, &error) != 1 || error > 0 || output[0] != 0xe9 || iterator.index != 2 || !needed) { die("the Windows Unicode composition boundary check failed"); }
	error = 0;
	windows_uiter_setString(&iterator, emoji, 3);
	if (windows_unorm_next(&iterator, output, 16, 2, 0x20, 1, &needed, &error) != 2 || error > 0 || output[0] != 0xd83d || output[1] != 0xde00 || iterator.index != 2 || needed) { die("the Windows Unicode surrogate/filter check failed"); }
	error = 0;
	windows_uiter_setString(&iterator, accent, 2);
	if (windows_unorm_next(&iterator, NULL, 0, 2, 0, 1, &needed, &error) != 2 || error != 15 || iterator.index != 1) { die("the Windows Unicode overflow check failed"); }
	char name[128];
	error = 0;
	if (windows_u_charName(0x1f600, 0, name, sizeof name, &error) <= 0 || error > 0 || !windows_u_isgraph('a')) { die("the Windows Unicode character check failed"); }
	void *database = NULL;
	if (windows_sqlite_open_v2(":memory:", &database, 6, NULL) != 0 || !database) { die("the Windows SQLite check failed"); }
	sh_sqlite3_close(database);
	fprintf(stdout, "PASS modern Windows calling conventions, C++ strings, Unicode and SQLite\n");
	return 0;
}
