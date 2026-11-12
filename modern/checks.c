// Verify the new runtime primitives with synthetic inputs and no Apple components.
#define main prototype_host_main
#include "host.c"
#undef main

static cfobj *parse_xml(const char *text) {
	cfobj *data = sh_CFDataCreate(NULL, (const unsigned char *)text, strlen(text));
	cfobj *value = sh_CFPropertyListCreateFromXMLData(NULL, data, 0, NULL);
	sh_CFRelease(data);
	return value;
}

int main(void) {
#ifdef _WIN64
	if (modern_windows_runtime_check()) { return 31; }
#endif
	cfobj *dictionary = parse_xml("<?xml version=\"1.0\"?><plist version=\"1.0\"><dict><key>a&amp;b</key><array><integer>7</integer><string>&#x41;</string><true/></array></dict></plist>");
	if (!dictionary || dictionary->kind != CF_DICT || dictionary->nbytes != 1) { return 1; }
	cfobj *array = (cfobj *)sh_CFDictionaryGetValue(dictionary, cf_pinned("a&b"));
	if (!array || array->kind != CF_ARRAY || array->nbytes != 3) { return 2; }
	cfobj **entries = (cfobj **)array->bytes;
	if (entries[0]->kind != CF_NUMBER || entries[0]->num != 7 || strcmp(cf_cstr(entries[1]), "A") || entries[2]->kind != CF_BOOLEAN || entries[2]->num != 1) { return 3; }
	const char *invalid[] = {
		"<plist><dict><key>missing</key></dict></plist>",
		"<plist><string>&unknown;</string></plist>",
		"<plist><string>&#x110000;</string></plist>",
		"<plist><string>&#0;</string></plist>",
		"<plist><integer>no</integer></plist>",
		"<plist><array></plist>",
		"<plist><string>x</string></plist>trailing"
	};
	for (unsigned index = 0; index < sizeof(invalid) / sizeof(invalid[0]); index++) {
		if (parse_xml(invalid[index])) { return 10 + index; }
	}
	if (modern_contains_emoji(cf_pinned("ASCII text 123"))) { return 20; }
	void *true_slot = modern_foundation_constant("_kCFBooleanTrue");
	cfobj *boolean = (cfobj *)GHOST(*(gptr *)true_slot);
	if (boolean->kind != CF_BOOLEAN || boolean->num != 1) { return 21; }
	void *semaphore = modern_semaphore_create(0);
	if (!semaphore || modern_semaphore_wait(semaphore, 0) != 1) { return 22; }
	modern_semaphore_signal(semaphore);
	if (modern_semaphore_wait(semaphore, 0) != 0) { return 23; }
	CloseHandle(semaphore);
	if (timeline_check()) { return 24; }
	cfobj *unicode = modern_text("caf\xc3\xa9 \xf0\x9f\x98\x80");
	uint16_t characters[7];
	if (modern_string_length(unicode) != 7) { return 25; }
	modern_string_characters(unicode, 0, 7, characters);
	if (characters[3] != 0xe9 || characters[5] != 0xd83d || characters[6] != 0xde00) { return 26; }
	cfobj *copy = modern_string_copy(NULL, unicode);
	if (strcmp(cf_cstr(copy), "caf\xc3\xa9 \xf0\x9f\x98\x80")) { return 27; }
	cfobj *suffix = modern_text(" again");
	modern_string_append(copy, suffix);
	if (modern_string_length(copy) != 13 || strcmp(cf_cstr(copy), "caf\xc3\xa9 \xf0\x9f\x98\x80 again")) { return 28; }
	if (!modern_contains_emoji(unicode) || modern_contains_emoji(modern_text("caf\xc3\xa9"))) { return 29; }
	char formatted[128];
	sh_sprintf(formatted, "%s %ld %.1f", "64-bit", (glong)12345678901LL, 1.5);
	if (strcmp(formatted, "64-bit 12345678901 1.5")) { return 30; }
	fprintf(stdout, "PASS modern property lists, constants, ASCII emoji check, semaphore timeout/signal and 64-bit audio timeline\n");
	return 0;
}
