// Preserve Unicode text at the modern engine's UTF-16 boundary while keeping filesystem strings in UTF-8.
#define MODERN_MAXIMUM_TEXT_UNITS (4 * 1024 * 1024)
static int property_utf8(char *output, unsigned value);

static uint16_t *modern_units(const void *string, size_t *length, int *owned) {
	*owned = 0;
	*length = 0;
	if (!string) { return NULL; }
	const cfstring *shape = string;
	if (cf_ours(string) && ((const cfobj *)string)->macroman == 2) {
		*length = shape->len;
		return (uint16_t *)((const cfobj *)string)->bytes;
	}
	if (!cf_ours(string) && (shape->flags & 0x10)) {
		*length = shape->len;
		return (uint16_t *)GHOST(shape->cstr);
	}
	const unsigned char *bytes = (const unsigned char *)cf_cstr(string);
	if (!bytes) { return NULL; }
	size_t size = strlen((const char *)bytes);
	if (size > MODERN_MAXIMUM_TEXT_UNITS) { die("the modern text buffer exceeds its limit"); }
	uint16_t *units = malloc((size + 1) * sizeof(*units));
	if (!units) { die("cannot allocate modern Unicode text"); }
	const unsigned char *end = bytes + size;
	int macroman = cf_ours(string) && ((const cfobj *)string)->macroman == 1;
	while (bytes < end) {
		unsigned value = *bytes++;
		if (macroman && value >= 0x80) { value = CF_MACROMAN[value - 0x80]; }
		else if (value >= 0x80) {
			unsigned remaining, minimum;
			if (value >= 0xc2 && value <= 0xdf) { value &= 31; remaining = 1; minimum = 0x80; }
			else if (value >= 0xe0 && value <= 0xef) { value &= 15; remaining = 2; minimum = 0x800; }
			else if (value >= 0xf0 && value <= 0xf4) { value &= 7; remaining = 3; minimum = 0x10000; }
			else { die("Alex received invalid UTF-8 text"); }
			while (remaining--) {
				if (bytes == end || (*bytes & 0xc0) != 0x80) { die("Alex received truncated UTF-8 text"); }
				value = (value << 6) | (*bytes++ & 63);
			}
			if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) { die("Alex received an invalid Unicode character"); }
		}
		if (value > 0xffff) {
			value -= 0x10000;
			units[(*length)++] = 0xd800 | (value >> 10);
			units[(*length)++] = 0xdc00 | (value & 1023);
		}
		else { units[(*length)++] = value; }
	}
	*owned = 1;
	return units;
}

static void modern_store_units(cfobj *string, const uint16_t *units, size_t length) {
	if (!cf_ours(string) || string->kind != CF_STRING || length > MODERN_MAXIMUM_TEXT_UNITS) { die("invalid modern string update"); }
	uint16_t *copy = malloc((length + 1) * sizeof(*copy));
	char *utf8 = malloc(length * 4 + 1);
	if (!copy || !utf8) { die("cannot allocate modern Unicode text"); }
	if (length) { memcpy(copy, units, length * 2); }
	copy[length] = 0;
	size_t size = 0;
	for (size_t index = 0; index < length; index++) {
		unsigned value = units[index];
		if (value >= 0xd800 && value <= 0xdbff && index + 1 < length && units[index + 1] >= 0xdc00 && units[index + 1] <= 0xdfff) {
			value = 0x10000 + ((value - 0xd800) << 10) + units[++index] - 0xdc00;
		}
		else if (value >= 0xd800 && value <= 0xdfff) { value = 0xfffd; }
		size += property_utf8(utf8 + size, value);
	}
	utf8[size] = 0;
	if (string->macroman == 2) { free(string->bytes); }
	free(string->big);
	string->big = NULL;
	if (size < sizeof(string->buf)) {
		memcpy(string->buf, utf8, size + 1);
		free(utf8);
		string->str.cstr = GP(string->buf);
	}
	else { string->big = utf8; string->str.cstr = GP(utf8); }
	string->bytes = (unsigned char *)copy;
	string->nbytes = length * 2;
	string->str.len = length;
	string->macroman = 2;
}

static cfobj *modern_text(const char *utf8) {
	cfobj *string = cf_new(utf8);
	if (!string) { return NULL; }
	size_t length;
	int owned;
	uint16_t *units = modern_units(string, &length, &owned);
	modern_store_units(string, units, length);
	if (owned) { free(units); }
	return string;
}

static void *__cdecl modern_string_from_characters(void *allocator, const uint16_t *characters, glong length, void *deallocator) {
	(void)allocator;
	(void)deallocator;
	if (length < 0 || length > MODERN_MAXIMUM_TEXT_UNITS || (!characters && length)) { return NULL; }
	cfobj *string = cf_new("");
	if (string) { modern_store_units(string, characters, length); }
	return string;
}

static void *__cdecl modern_string_copy(void *allocator, const void *source) {
	if (!source) { return NULL; }
	size_t length;
	int owned;
	uint16_t *units = modern_units(source, &length, &owned);
	void *result = modern_string_from_characters(allocator, units, length, NULL);
	if (owned) { free(units); }
	return result;
}

static glong __cdecl modern_string_length(const void *string) {
	size_t length;
	int owned;
	uint16_t *units = modern_units(string, &length, &owned);
	if (owned) { free(units); }
	return length;
}

static const uint16_t *__cdecl modern_string_pointer(const void *string) {
	if (cf_ours(string) && ((const cfobj *)string)->macroman == 2) { return (const uint16_t *)((const cfobj *)string)->bytes; }
	if (string && !cf_ours(string) && (((const cfstring *)string)->flags & 0x10)) { return (const uint16_t *)GHOST(((const cfstring *)string)->cstr); }
	return NULL;
}

static void __cdecl modern_string_characters(const void *string, glong location, glong count, uint16_t *output) {
	size_t length;
	int owned;
	uint16_t *units = modern_units(string, &length, &owned);
	if (location < 0 || count < 0 || (uint64_t)location > length || (uint64_t)count > length - location) { die("modern string range is outside its text"); }
	if (count) { memcpy(output, units + location, count * 2); }
	if (owned) { free(units); }
}

static uint16_t __cdecl modern_string_character(const void *string, glong location) {
	uint16_t value;
	modern_string_characters(string, location, 1, &value);
	return value;
}

static void __cdecl modern_string_replace(void *string, glong location, glong count, const void *replacement) {
	if (!cf_ours(string)) { die("cannot modify a foreign constant string"); }
	size_t length, replacement_length;
	int owned, replacement_owned;
	uint16_t *units = modern_units(string, &length, &owned);
	uint16_t *inserted = modern_units(replacement, &replacement_length, &replacement_owned);
	if (location < 0 || count < 0 || (uint64_t)location > length || (uint64_t)count > length - location || replacement_length > MODERN_MAXIMUM_TEXT_UNITS - (length - count)) { die("invalid modern string replacement"); }
	size_t result_length = length - count + replacement_length;
	uint16_t *result = malloc((result_length + 1) * 2);
	if (!result) { die("cannot allocate modern string replacement"); }
	memcpy(result, units, location * 2);
	if (replacement_length) { memcpy(result + location, inserted, replacement_length * 2); }
	memcpy(result + location + replacement_length, units + location + count, (length - location - count) * 2);
	modern_store_units(string, result, result_length);
	free(result);
	if (owned) { free(units); }
	if (replacement_owned) { free(inserted); }
}

static void __cdecl modern_string_append(void *string, const void *other) { modern_string_replace(string, modern_string_length(string), 0, other); }
static void __cdecl modern_string_insert(void *string, glong location, const void *other) { modern_string_replace(string, location, 0, other); }
static void *__cdecl modern_string_mutable(void *allocator, glong maximum) { (void)allocator; (void)maximum; return modern_text(""); }
static void *__cdecl modern_string_mutable_copy(void *allocator, glong maximum, const void *source) { (void)maximum; return modern_string_copy(allocator, source); }
static void __cdecl modern_string_append_characters(void *string, const uint16_t *characters, glong count) {
	void *other = modern_string_from_characters(NULL, characters, count, NULL);
	if (!other) { die("invalid characters appended to modern text"); }
	modern_string_append(string, other);
	sh_CFRelease(other);
}
