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

typedef struct {
	HANDLE entered, release;
	volatile LONG timed_out;
	int value, order;
} queue_check;

static void __cdecl queue_hold(void *argument) {
	queue_check *check = argument;
	SetEvent(check->entered);
	if (WaitForSingleObject(check->release, 2000) != WAIT_OBJECT_0) {
		InterlockedExchange(&check->timed_out, 1);
	}
	check->order = 1;
}

typedef struct {
	struct blk_layout header;
	queue_check *check;
	int captured;
} check_block;

static void __cdecl queue_captured(void *argument) {
	check_block *block = argument;
	block->check->value = block->captured;
	block->check->order = block->check->order == 1 ? 2 : -1;
}

static void __cdecl queue_barrier(void *argument) {
	queue_check *check = argument;
	check->order = check->order == 2 ? 3 : -1;
}

static int queue_check_run(void) {
	queue_check check = {0};
	check.entered = CreateEvent(NULL, FALSE, FALSE, NULL);
	check.release = CreateEvent(NULL, FALSE, FALSE, NULL);
	void *queue = sh_dispatch_queue_create("test.serial", NULL);
	struct blk_descriptor descriptor = {0};
	descriptor.size = sizeof(check_block);
	check_block block = {0};
	block.header.invoke = GP(queue_captured);
	block.header.descriptor = GP(&descriptor);
	block.check = &check;
	block.captured = 42;
	sh_dispatch_async_f(queue, &check, queue_hold);
	if (WaitForSingleObject(check.entered, 2000) != WAIT_OBJECT_0 || check.timed_out) { return 1; }
	sh_dispatch_async(queue, &block);
	block.captured = 99;
	SetEvent(check.release);
	sh_dispatch_sync_f(queue, &check, queue_barrier);
	CloseHandle(check.entered);
	CloseHandle(check.release);
	if (check.timed_out || check.order != 3 || check.value != 42) { return 2; }
	return 0;
}

typedef struct {
	mtx mutex;
	cnd condition;
	HANDLE entered;
	int signalled;
} condition_check;

static DWORD WINAPI condition_signal_thread(void *argument) {
	condition_check *check = argument;
	WaitForSingleObject(check->entered, INFINITE);
	sh_mutex_lock(&check->mutex);
	check->signalled = 1;
	sh_cond_signal(&check->condition);
	sh_mutex_unlock(&check->mutex);
	return 0;
}

static int condition_check_run(void) {
	condition_check check = {0};
	check.entered = CreateEvent(NULL, FALSE, FALSE, NULL);
	sh_mutex_init(&check.mutex, NULL);
	sh_cond_init(&check.condition, NULL);
	sh_mutex_lock(&check.mutex);
	int64_t deadline[2] = {0};
	if (modern_condition_timedwait(&check.condition, &check.mutex, deadline) != 60) { return 1; }
	deadline[1] = 1000000000;
	if (modern_condition_timedwait(&check.condition, &check.mutex, deadline) != 22) { return 2; }
	HANDLE thread = CreateThread(NULL, 0, condition_signal_thread, &check, 0, NULL);
	if (!thread) { return 3; }
	SetEvent(check.entered);
	while (!check.signalled) {
		uint64_t target = wall_us_scaled() * 1000ULL + (uint64_t)(g_speed * 5000000000.0);
		deadline[0] = target / 1000000000ULL;
		deadline[1] = target % 1000000000ULL;
		if (modern_condition_timedwait(&check.condition, &check.mutex, deadline)) { return 4; }
	}
	sh_mutex_unlock(&check.mutex);
	if (WaitForSingleObject(thread, 5000) != WAIT_OBJECT_0) { return 5; }
	CloseHandle(thread);
	CloseHandle(check.entered);
	sh_cond_destroy(&check.condition);
	sh_mutex_destroy(&check.mutex);
	return 0;
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
	if (queue_check_run()) { return 32; }
	if (condition_check_run()) { return 33; }
	fprintf(stdout, "PASS modern property lists, Unicode strings, semaphore, queued block lifetime/order and 64-bit audio timeline\n");
	return 0;
}
