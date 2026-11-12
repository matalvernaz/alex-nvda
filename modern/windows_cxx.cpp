// Adapt the engine's Itanium string calls to the bundled open-source Windows libc++ runtime.
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <new>
#include <string>
#include <windows.h>

#define GUEST __attribute__((sysv_abi))
// GCC's Windows headers import this legacy spelling; LLVM's UCRT supplies its compatible implementation.
extern "C" {
	int (*__imp__snprintf)(char *, size_t, const char *, ...) = &_snprintf;
}
using Text = std::string;
static_assert(sizeof(Text) == 24, "The Intel engine requires libc++'s three-word string layout");

static void GUEST cxx_unavailable() {
	std::fputs("alex_host: the speech engine raised a C++ exception; this utterance cannot continue\n", stderr);
	std::fflush(stderr);
	std::exit(3);
}

static void *GUEST cxx_allocate(size_t size) {
	void *memory = std::malloc(size);
	if (!memory) { cxx_unavailable(); }
	return memory;
}

static void GUEST cxx_delete(void *memory) { std::free(memory); }
static void *GUEST cxx_exception_allocate(size_t size) { return cxx_allocate(size); }
static void *GUEST cxx_dynamic_cast(const void *object, const void *source, const void *target, ptrdiff_t hint) {
	using Function = void *(*)(const void *, const void *, const void *, ptrdiff_t);
	HMODULE library = LoadLibraryW(L"libc++.dll");
	Function function = library ? reinterpret_cast<Function>(GetProcAddress(library, "__dynamic_cast")) : nullptr;
	if (!function) { cxx_unavailable(); }
	return function(object, source, target, hint);
}

static Text *GUEST text_append(Text *text, const char *value) { text->append(value); return text; }
static Text *GUEST text_append_bytes(Text *text, const char *value, size_t length) { text->append(value, length); return text; }
static Text *GUEST text_append_fill(Text *text, size_t count, char value) { text->append(count, value); return text; }
static Text *GUEST text_assign(Text *text, const char *value) { text->assign(value); return text; }
static Text *GUEST text_assign_bytes(Text *text, const char *value, size_t length) { text->assign(value, length); return text; }
static Text *GUEST text_assign_copy(Text *text, const Text *value) { *text = *value; return text; }
static void GUEST text_push_back(Text *text, char value) { text->push_back(value); }
static Text *GUEST text_insert(Text *text, size_t position, const char *value) { text->insert(position, value); return text; }
static Text *GUEST text_insert_bytes(Text *text, size_t position, const char *value, size_t length) { text->insert(position, value, length); return text; }
static Text *GUEST text_insert_fill(Text *text, size_t position, size_t count, char value) { text->insert(position, count, value); return text; }
static const char *GUEST text_insert_iterator(Text *text, const char *position, char value) {
	size_t offset = position - text->data();
	text->insert(offset, 1, value);
	return text->data() + offset;
}
static Text *GUEST text_replace(Text *text, size_t position, size_t count, const char *value, size_t length) { text->replace(position, count, value, length); return text; }
static void GUEST text_construct_range(Text *text, const Text *value, size_t position, size_t count, const void *allocator) {
	(void)allocator;
	new (text) Text(*value, position, count);
}
static Text *GUEST text_add_prefix(Text *output, const char *prefix, const Text *text) { new (output) Text(prefix + *text); return output; }
static void GUEST sort_unsigned(unsigned *first, unsigned *last, void *comparison) {
	(void)comparison;
	std::sort(first, last);
}

extern "C" int modern_windows_cxx_check() {
	Text short_text("hi");
	Text long_text(128, 'x');
	const unsigned char *short_bytes = reinterpret_cast<const unsigned char *>(&short_text);
	const size_t *long_words = reinterpret_cast<const size_t *>(&long_text);
	if (short_bytes[0] != 4 || short_bytes[1] != 'h' || short_bytes[2] != 'i' || long_words[1] != 128 || long_words[2] != reinterpret_cast<size_t>(long_text.data())) { return 1; }
	text_append_bytes(&short_text, " there", 6);
	if (short_text != "hi there") { return 2; }
	unsigned values[] = { 3, 1, 2 };
	sort_unsigned(values, values + 3, nullptr);
	if (values[0] != 1 || values[2] != 3) { return 3; }
	return 0;
}

extern "C" void *modern_windows_cxx_symbol(const char *name) {
	static const struct { const char *name; void *function; } functions[] = {
#define TEXT_SYMBOL(suffix, function) { "__ZNSt3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEE" suffix, reinterpret_cast<void *>(function) }
		TEXT_SYMBOL("6appendEPKc", text_append), TEXT_SYMBOL("6appendEPKcm", text_append_bytes), TEXT_SYMBOL("6appendEmc", text_append_fill),
		TEXT_SYMBOL("6assignEPKc", text_assign), TEXT_SYMBOL("6assignEPKcm", text_assign_bytes), TEXT_SYMBOL("aSERKS5_", text_assign_copy),
		TEXT_SYMBOL("9push_backEc", text_push_back), TEXT_SYMBOL("6insertEmPKc", text_insert), TEXT_SYMBOL("6insertEmPKcm", text_insert_bytes),
		TEXT_SYMBOL("6insertEmmc", text_insert_fill), TEXT_SYMBOL("6insertENS_11__wrap_iterIPKcEEc", text_insert_iterator),
		TEXT_SYMBOL("7replaceEmmPKcm", text_replace), TEXT_SYMBOL("C2ERKS5_mmRKS4_", text_construct_range),
		{ "__ZNSt3__1plIcNS_11char_traitsIcEENS_9allocatorIcEEEENS_12basic_stringIT_T0_T1_EEPKS6_RKS9_", reinterpret_cast<void *>(text_add_prefix) },
		{ "__ZNSt3__16__sortIRNS_6__lessIjjEEPjEEvT0_S5_T_", reinterpret_cast<void *>(sort_unsigned) },
		{ "__Znwm", reinterpret_cast<void *>(cxx_allocate) }, { "__Znam", reinterpret_cast<void *>(cxx_allocate) },
		{ "__ZdlPv", reinterpret_cast<void *>(cxx_delete) }, { "__ZdaPv", reinterpret_cast<void *>(cxx_delete) },
		{ "___cxa_allocate_exception", reinterpret_cast<void *>(cxx_exception_allocate) },
		{ "___dynamic_cast", reinterpret_cast<void *>(cxx_dynamic_cast) },
		{ "___cxa_free_exception", reinterpret_cast<void *>(cxx_delete) },
		{ "___cxa_throw", reinterpret_cast<void *>(cxx_unavailable) }, { "___cxa_rethrow", reinterpret_cast<void *>(cxx_unavailable) },
		{ "___cxa_begin_catch", reinterpret_cast<void *>(cxx_unavailable) }, { "___cxa_end_catch", reinterpret_cast<void *>(cxx_unavailable) },
		{ "___gxx_personality_v0", reinterpret_cast<void *>(cxx_unavailable) }, { "__Unwind_Resume", reinterpret_cast<void *>(cxx_unavailable) },
		{ "__ZSt9terminatev", reinterpret_cast<void *>(cxx_unavailable) },
	};
	for (const auto &entry : functions) {
		if (!std::strcmp(name, entry.name)) { return entry.function; }
	}
	// RTTI and vtable addresses are data. Function imports always need an explicit ABI adapter.
	if (!std::strncmp(name, "__ZTI", 5) || !std::strncmp(name, "__ZTV", 5)) {
		HMODULE library = LoadLibraryW(L"libc++.dll");
		return library ? reinterpret_cast<void *>(GetProcAddress(library, name + 1)) : nullptr;
	}
	return nullptr;
}
