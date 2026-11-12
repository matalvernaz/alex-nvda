// Read XML property lists used by speech dictionaries instead of silently discarding them.
typedef struct {
	const char *cursor;
	const char *end;
	unsigned depth;
	int failed;
} property_reader;

static const unsigned short *modern_string_characters_pointer(const void *string) {
	// CoreFoundation permits NULL here for strings whose storage is not contiguous UTF-16; the caller then uses GetCharacters.
	(void)string;
	return NULL;
}

static int modern_contains_emoji(const void *string) {
	const char *text = cf_cstr(string);
	if (!text) { die("emoji detection received an invalid string"); }
	for (const unsigned char *character = (const unsigned char *)text; *character; character++) {
		if (*character >= 0x80) {
			die("the modern prototype currently supports ASCII comparisons only; Unicode emoji handling is not ported");
		}
	}
	return 0;
}

static void *modern_foundation_constant(const char *name) {
	static const char *names[] = {
		"_kCFAllocatorNull", "_kCFBooleanFalse", "_kCFBooleanTrue", "_kCFErrorDomainOSStatus",
		"_kCFLocaleLanguageCode", "_kCFPreferencesAnyApplication", "_kCFPreferencesAnyUser", "_kCFPreferencesCurrentHost"
	};
	static gptr values[sizeof(names) / sizeof(names[0])];
	static gptr callbacks[6];
	if (!strcmp(name, "_kCFTypeArrayCallBacks") || !strcmp(name, "_kCFTypeDictionaryKeyCallBacks") || !strcmp(name, "_kCFTypeDictionaryValueCallBacks")) {
		return callbacks;
	}
	for (unsigned index = 0; index < sizeof(names) / sizeof(names[0]); index++) {
		if (strcmp(name, names[index])) { continue; }
		if (!values[index]) {
			cfobj *value;
			if (index == 1 || index == 2) {
				value = cf_number(index == 2);
				value->kind = CF_BOOLEAN;
				value->rc = CF_PINNED;
			}
			else { value = cf_pinned(names[index]); }
			values[index] = GP(value);
		}
		return &values[index];
	}
	return NULL;
}

static void property_dictionary_add(cfobj *dictionary, cfobj *key, cfobj *value) {
	unsigned count = dictionary->nbytes;
	void **entries = GMEM_REALLOC(dictionary->bytes, (size_t)(count + 1) * 2 * sizeof(void *));
	if (!entries) {
		die("cannot allocate property list dictionary entries");
	}
	dictionary->bytes = (unsigned char *)entries;
	entries[count * 2] = sh_CFRetain(key);
	entries[count * 2 + 1] = sh_CFRetain(value);
	dictionary->nbytes++;
}

static void property_skip_space(property_reader *reader) {
	while (reader->cursor < reader->end && isspace((unsigned char)*reader->cursor)) {
		reader->cursor++;
	}
}

static int property_take(property_reader *reader, const char *text) {
	size_t size = strlen(text);
	if ((size_t)(reader->end - reader->cursor) < size || memcmp(reader->cursor, text, size)) {
		return 0;
	}
	reader->cursor += size;
	return 1;
}

static int property_utf8(char *output, unsigned value) {
	if (value < 0x80) {
		output[0] = value;
		return 1;
	}
	if (value < 0x800) {
		output[0] = 0xc0 | value >> 6;
		output[1] = 0x80 | (value & 63);
		return 2;
	}
	if (value < 0x10000) {
		output[0] = 0xe0 | value >> 12;
		output[1] = 0x80 | ((value >> 6) & 63);
		output[2] = 0x80 | (value & 63);
		return 3;
	}
	output[0] = 0xf0 | value >> 18;
	output[1] = 0x80 | ((value >> 12) & 63);
	output[2] = 0x80 | ((value >> 6) & 63);
	output[3] = 0x80 | (value & 63);
	return 4;
}

static char *property_text(property_reader *reader, const char *closing) {
	char *text = malloc((size_t)(reader->end - reader->cursor) + 1);
	if (!text) {
		reader->failed = 1;
		return NULL;
	}
	size_t count = 0;
	while (reader->cursor < reader->end && *reader->cursor != '<') {
		if (*reader->cursor != '&') {
			text[count++] = *reader->cursor++;
			continue;
		}
		reader->cursor++;
		const char *entity = reader->cursor;
		const char *semicolon = memchr(entity, ';', reader->end - entity);
		if (!semicolon || semicolon - entity > 16) {
			reader->failed = 1;
			break;
		}
		unsigned value = 0;
		if (property_take(reader, "amp;")) { value = '&'; }
		else if (property_take(reader, "lt;")) { value = '<'; }
		else if (property_take(reader, "gt;")) { value = '>'; }
		else if (property_take(reader, "quot;")) { value = '"'; }
		else if (property_take(reader, "apos;")) { value = '\''; }
		else if (property_take(reader, "#")) {
			unsigned base = property_take(reader, "x") ? 16 : 10;
			const char *digits = reader->cursor;
			while (reader->cursor < semicolon) {
				unsigned char character = *reader->cursor++;
				unsigned digit = character >= '0' && character <= '9' ? character - '0' : character >= 'a' && character <= 'f' ? character - 'a' + 10 : character >= 'A' && character <= 'F' ? character - 'A' + 10 : 99;
				if (digit >= base || value > 0x10ffff / base) {
					reader->failed = 1;
					break;
				}
				value = value * base + digit;
			}
			if (reader->cursor == digits || !property_take(reader, ";")) { reader->failed = 1; }
		}
		else { reader->failed = 1; }
		if (reader->failed || value == 0 || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) {
			reader->failed = 1;
			break;
		}
		count += property_utf8(text + count, value);
	}
	text[count] = 0;
	if (!property_take(reader, closing)) {
		reader->failed = 1;
	}
	return text;
}

static cfobj *property_value(property_reader *reader) {
	property_skip_space(reader);
	if (++reader->depth > 64) {
		reader->failed = 1;
		reader->depth--;
		return NULL;
	}
	cfobj *value = NULL;
	if (property_take(reader, "<dict/>") || property_take(reader, "<dict />")) { value = cf_container(CF_DICT, 0); }
	else if (property_take(reader, "<array/>") || property_take(reader, "<array />")) { value = cf_container(CF_ARRAY, 0); }
	else if (property_take(reader, "<string/>") || property_take(reader, "<string />")) { value = cf_new(""); }
	else if (property_take(reader, "<true/>")) { value = cf_number(1); if (value) { value->kind = CF_BOOLEAN; } }
	else if (property_take(reader, "<false/>")) { value = cf_number(0); if (value) { value->kind = CF_BOOLEAN; } }
	else if (property_take(reader, "<dict>")) {
		value = cf_container(CF_DICT, 0);
		while (value && !reader->failed) {
			property_skip_space(reader);
			if (property_take(reader, "</dict>")) { break; }
			if (!property_take(reader, "<key>")) { reader->failed = 1; break; }
			char *name = property_text(reader, "</key>");
			cfobj *key = name ? cf_new(name) : NULL;
			free(name);
			cfobj *child = property_value(reader);
			if (!key || !child) { reader->failed = 1; }
			else { property_dictionary_add(value, key, child); }
			sh_CFRelease(key);
			sh_CFRelease(child);
		}
	}
	else if (property_take(reader, "<array>")) {
		value = cf_container(CF_ARRAY, 0);
		while (value && !reader->failed) {
			property_skip_space(reader);
			if (property_take(reader, "</array>")) { break; }
			cfobj *child = property_value(reader);
			if (!child) { reader->failed = 1; }
			else { sh_CFArrayAppendValue(value, child); }
			sh_CFRelease(child);
		}
	}
	else {
		const char *closing = NULL;
		int number = 0;
		if (property_take(reader, "<string>")) { closing = "</string>"; }
		else if (property_take(reader, "<integer>")) { closing = "</integer>"; number = 1; }
		else if (property_take(reader, "<real>")) { closing = "</real>"; number = 1; }
		if (closing) {
			char *text = property_text(reader, closing);
			if (text && !reader->failed) {
				if (number) {
					char *end;
					double converted = strtod(text, &end);
					if (end == text || *end) { reader->failed = 1; }
					else { value = cf_number(converted); }
				}
				else { value = cf_new(text); }
			}
			free(text);
		}
	}
	reader->depth--;
	if (!value || reader->failed) {
		sh_CFRelease(value);
		reader->failed = 1;
		return NULL;
	}
	return value;
}

static void *sh_CFPropertyListCreateFromXMLData(void *allocator, const void *data, glong options, gptr *error) {
	(void)allocator;
	(void)options;
	if (error) { *error = 0; }
	const char *bytes = sh_CFDataGetBytePtr(data);
	size_t size = sh_CFDataGetLength(data);
	if (!bytes) { return NULL; }
	property_reader reader = { bytes, bytes + size, 0, 0 };
	property_skip_space(&reader);
	while (reader.cursor + 2 < reader.end && reader.cursor[0] == '<' && (reader.cursor[1] == '?' || reader.cursor[1] == '!')) {
		const char *end = memchr(reader.cursor, '>', reader.end - reader.cursor);
		if (!end) { return NULL; }
		reader.cursor = end + 1;
		property_skip_space(&reader);
	}
	if (!property_take(&reader, "<plist")) { return NULL; }
	const char *tag_end = memchr(reader.cursor, '>', reader.end - reader.cursor);
	if (!tag_end) { return NULL; }
	reader.cursor = tag_end + 1;
	cfobj *value = property_value(&reader);
	property_skip_space(&reader);
	if (!property_take(&reader, "</plist>")) { reader.failed = 1; }
	property_skip_space(&reader);
	if (reader.failed || reader.cursor != reader.end) {
		sh_CFRelease(value);
		if (error) { *error = GP(cf_new("Unsupported or invalid XML property list")); }
		return NULL;
	}
	return value;
}

static void *sh_CFReadStreamCreateWithFile(void *allocator, const void *url) {
	(void)allocator;
	const char *path = cf_cstr(url);
	return path ? cf_data(path) : NULL;
}

static int sh_CFReadStreamOpen(const void *stream) {
	return cf_ours(stream) && ((const cfobj *)stream)->kind == CF_DATA;
}

static void sh_CFReadStreamClose(void *stream) {
	(void)stream;
}

static void *sh_CFPropertyListCreateWithStream(void *allocator, const void *stream, glong length, glong options, glong *format, gptr *error) {
	if (length < 0 || !sh_CFReadStreamOpen(stream)) {
		return NULL;
	}
	void *result = sh_CFPropertyListCreateFromXMLData(allocator, stream, options, error);
	if (result && format) { *format = 100; }
	return result;
}

static void *sh_CFPropertyListCreateWithData(void *allocator, const void *data, glong options, glong *format, gptr *error) {
	return sh_CFPropertyListCreateWithStream(allocator, data, 0, options, format, error);
}
