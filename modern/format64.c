// Format Darwin x64 arguments without handing their register-save area to a Windows va_list reader.
static int modern_vformat(char *output, size_t capacity, const char *format, GUEST_VA_LIST arguments) {
	size_t written = 0;
	for (const char *cursor = format; *cursor;) {
		if (*cursor != '%') {
			if (written + 1 < capacity) { output[written] = *cursor; }
			written++;
			cursor++;
			continue;
		}
		cursor++;
		if (*cursor == '%') {
			if (written + 1 < capacity) { output[written] = '%'; }
			written++;
			cursor++;
			continue;
		}
		char conversion[64] = "%";
		size_t length = 1;
		while (*cursor && strchr("-+ #0.0123456789", *cursor)) {
			if (length >= sizeof(conversion) - 5) { die("speech format is too long"); }
			conversion[length++] = *cursor++;
		}
		if (*cursor == '*') { die("dynamic-width speech formats are not supported"); }
		int wide = 0;
		while (*cursor && strchr("hljzt", *cursor)) {
			if (*cursor != 'h') { wide = 1; }
			cursor++;
		}
		char type = *cursor++;
		char temporary[4096];
		int count;
		if (type == 's') {
			conversion[length++] = type;
			conversion[length] = 0;
			const char *text = GUEST_VA_ARG(arguments, const char *);
			count = snprintf(temporary, sizeof temporary, conversion, text ? text : "(null)");
		}
		else if (type == 'p') {
			conversion[length++] = type;
			conversion[length] = 0;
			count = snprintf(temporary, sizeof temporary, conversion, GUEST_VA_ARG(arguments, void *));
		}
		else if (strchr("diuoxXc", type)) {
			if (wide && type != 'c') { conversion[length++] = 'l'; conversion[length++] = 'l'; }
			conversion[length++] = type;
			conversion[length] = 0;
			if (wide && type != 'c') {
				if (type == 'd' || type == 'i') { count = snprintf(temporary, sizeof temporary, conversion, GUEST_VA_ARG(arguments, long long)); }
				else { count = snprintf(temporary, sizeof temporary, conversion, GUEST_VA_ARG(arguments, unsigned long long)); }
			}
			else if (type == 'd' || type == 'i' || type == 'c') { count = snprintf(temporary, sizeof temporary, conversion, GUEST_VA_ARG(arguments, int)); }
			else { count = snprintf(temporary, sizeof temporary, conversion, GUEST_VA_ARG(arguments, unsigned)); }
		}
		else if (strchr("fFeEgGaA", type)) {
			conversion[length++] = type;
			conversion[length] = 0;
			count = snprintf(temporary, sizeof temporary, conversion, GUEST_VA_ARG(arguments, double));
		}
		else { die("unsupported speech format conversion %c", type); }
		if (count < 0 || count >= (int)sizeof temporary) { die("speech diagnostic exceeds its formatting limit"); }
		for (int index = 0; index < count; index++) {
			if (written + 1 < capacity) { output[written] = temporary[index]; }
			written++;
		}
	}
	if (capacity) { output[written < capacity ? written : capacity - 1] = 0; }
	return (int)written;
}
