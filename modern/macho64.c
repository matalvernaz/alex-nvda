// Map Intel 64-bit speech components and resolve modern dyld fixups without Apple loader code.
#include <limits.h>

#define MODERN_CHAINED_FIXUPS 0x80000034u
#define MODERN_EXPORTS_TRIE 0x80000033u
#define MODERN_POINTER_64 2u
#define MODERN_POINTER_64_OFFSET 6u
#define MODERN_PAGE_NONE 0xffffu

static void require_slice(const image *component, uint64_t offset, uint64_t length) {
	if (offset > component->slice_size || length > component->slice_size - offset) {
		die("truncated Mach-O data in %s at 0x%llx", component->path, (unsigned long long)offset);
	}
}

static unsigned char *read_file(const char *path, size_t *length) {
	FILE *input = fopen(path, "rb");
	if (!input) {
		die("cannot open %s", path);
	}
	fseek(input, 0, SEEK_END);
	long size = ftell(input);
	if (size < (long)sizeof(mach_header)) {
		die("invalid Mach-O length in %s", path);
	}
	rewind(input);
	unsigned char *data = malloc((size_t)size);
	if (!data || fread(data, 1, size, input) != (size_t)size) {
		die("cannot read %s", path);
	}
	fclose(input);
	*length = (size_t)size;
	return data;
}

static unsigned char *find_i386(unsigned char *data, size_t length) {
	if (*(uint32_t *)data == MH_MAGIC) {
		return data;
	}
	if (*(uint32_t *)data != FAT_CIGAM || length < 8) {
		die("expected a 64-bit Intel Mach-O or universal binary");
	}
	uint32_t count = bswap(*(uint32_t *)(data + 4));
	if (count > (length - 8) / 20) {
		die("truncated universal Mach-O header");
	}
	for (uint32_t index = 0; index < count; index++) {
		uint32_t *entry = (uint32_t *)(data + 8 + index * 20);
		uint32_t offset = bswap(entry[2]);
		uint32_t size = bswap(entry[3]);
		if (bswap(entry[0]) != CPU_TYPE_X86) {
			continue;
		}
		if (offset > length || size > length - offset || size < sizeof(mach_header)) {
			die("invalid Intel slice bounds");
		}
		return data + offset;
	}
	die("no Intel 64-bit slice in this component");
	return NULL;
}

static void map_image(image *component) {
	require_slice(component, 0, sizeof(mach_header));
	mach_header *header = (mach_header *)component->slice;
	if (header->magic != MH_MAGIC || header->cputype != CPU_TYPE_X86) {
		die("expected Intel 64-bit Mach-O in %s", component->path);
	}
	require_slice(component, sizeof(*header), header->sizeofcmds);
	uint64_t lowest = UINT64_MAX;
	uint64_t highest = 0;
	int cached = 0;
	size_t offset = sizeof(*header);
	for (unsigned index = 0; index < header->ncmds; index++) {
		require_slice(component, offset, sizeof(load_command));
		load_command *command = (load_command *)(component->slice + offset);
		if (command->cmdsize < sizeof(*command)) {
			die("invalid Mach-O command size");
		}
		require_slice(component, offset, command->cmdsize);
		if (command->cmd == LC_SEGMENT) {
			if (command->cmdsize < sizeof(segment_command)) {
				die("truncated 64-bit segment command");
			}
			segment_command *segment = (segment_command *)command;
			if (!strcmp(segment->segname, "__LINKEDIT")) {
				offset += command->cmdsize;
				continue;
			}
			if (segment->vmsize) {
				if (segment->vmaddr < lowest) {
					lowest = segment->vmaddr;
				}
				if (segment->vmsize > UINT64_MAX - segment->vmaddr) {
					die("overflowing segment address");
				}
				if (segment->vmaddr + segment->vmsize > highest) {
					highest = segment->vmaddr + segment->vmsize;
				}
			}
		}
		offset += command->cmdsize;
	}
	if (lowest == UINT64_MAX || highest - lowest > SIZE_MAX || highest == lowest) {
		die("invalid 64-bit component address range");
	}
	component->lo = lowest;
	component->hi = highest;
	cached = lowest > UINT32_MAX;
	uint64_t reservation = lowest & ~0xffffULL;
	unsigned char *memory = VirtualAlloc(cached ? (void *)reservation : NULL, highest - reservation, MEM_RESERVE, PAGE_NOACCESS);
	if (!memory) {
		die("cannot map 64-bit component %s", component->path);
	}
	component->slide = (uintptr_t)memory - reservation;
	if (g_verbose) {
		printf("%s: 64-bit image mapped at %p, %llu bytes\n", component->path, memory, (unsigned long long)(highest - lowest));
	}

	// Keep the original file offsets for link-edit tables while copying executable segments to their mapped addresses.
	offset = sizeof(*header);
	for (unsigned index = 0; index < header->ncmds; index++) {
		load_command *command = (load_command *)(component->slice + offset);
		if (command->cmd == LC_SEGMENT) {
			segment_command *segment = (segment_command *)command;
			require_slice(component, segment->fileoff, segment->filesize);
			if (segment->filesize > segment->vmsize || segment->nsects > (command->cmdsize - sizeof(*segment)) / sizeof(section)) {
				die("invalid 64-bit segment contents");
			}
			if (strcmp(segment->segname, "__LINKEDIT")) {
				uintptr_t first_page = (segment->vmaddr + component->slide) & ~(uintptr_t)4095;
				size_t page_bytes = (size_t)(segment->vmaddr + component->slide + segment->vmsize - first_page);
				if (page_bytes && !VirtualAlloc((void *)first_page, page_bytes, MEM_COMMIT, PAGE_EXECUTE_READWRITE)) {
					die("cannot commit a 64-bit component segment");
				}
				memcpy((void *)(segment->vmaddr + component->slide), component->slice + segment->fileoff, segment->filesize);
			}
			if (component->nsegs >= 16 || component->nsects + segment->nsects > 64) {
				die("too many segments or sections");
			}
			component->segaddr[component->nsegs++] = segment->vmaddr;
			section *sections = (section *)(segment + 1);
			for (unsigned section_index = 0; section_index < segment->nsects; section_index++) {
				component->sects[component->nsects++] = sections[section_index];
			}
		}
		else if (command->cmd == LC_SYMTAB) {
			symtab_command *symbols = (symtab_command *)command;
			require_slice(component, symbols->symoff, (uint64_t)symbols->nsyms * sizeof(nlist));
			require_slice(component, symbols->stroff, symbols->strsize);
			component->syms = (nlist *)(component->slice + symbols->symoff);
			component->nsyms = symbols->nsyms;
			component->strs = (char *)(component->slice + symbols->stroff);
			for (unsigned symbol_index = 0; symbol_index < symbols->nsyms; symbol_index++) {
				unsigned name = component->syms[symbol_index].n_strx;
				if (name >= symbols->strsize || !memchr(component->strs + name, 0, symbols->strsize - name)) {
					die("invalid symbol name");
				}
			}
		}
		else if (command->cmd == MODERN_CHAINED_FIXUPS || command->cmd == MODERN_EXPORTS_TRIE) {
			if (command->cmdsize < 16) {
				die("truncated link-edit command");
			}
			unsigned *values = (unsigned *)command;
			require_slice(component, values[2], values[3]);
			if (command->cmd == MODERN_CHAINED_FIXUPS) {
				component->fixups_offset = values[2];
				component->fixups_size = values[3];
			}
			else {
				component->exports_offset = values[2];
				component->exports_size = values[3];
			}
		}
		else if (command->cmd == LC_DYSYMTAB) {
			if (command->cmdsize < sizeof(dysymtab_command)) {
				die("truncated indirect symbol table command");
			}
			component->dys = (const dysymtab_command *)command;
			require_slice(component, component->dys->indirectsymoff, (uint64_t)component->dys->nindirectsyms * 4);
		}
		else if (command->cmd == LC_DYLD_INFO || command->cmd == LC_DYLD_INFO_ONLY) {
			component->info = (dyld_info_command *)command;
		}
		offset += command->cmdsize;
	}
}

static void *lookup_shim(const char *name) {
	for (unsigned index = 0; g_shims[index].name; index++) {
		if (!strcmp(g_shims[index].name, name)) {
			return g_shims[index].fn;
		}
	}
	void *constant = speech_const_lookup(name);
	if (!constant) { constant = modern_foundation_constant(name); }
	if (constant) {
		return constant;
	}
	if (!strcmp(name, "_uiter_setString") || !strcmp(name, "_unorm_next") || !strcmp(name, "_u_charName") || !strcmp(name, "_u_isgraph")) {
		static void *unicode;
		if (!unicode) { unicode = dlopen("libicuuc.so.76", RTLD_NOW | RTLD_LOCAL); }
		if (!unicode) { die("the modern prototype needs its ICU runtime: %s", dlerror()); }
		char versioned[128];
		snprintf(versioned, sizeof(versioned), "%s_76", name + 1);
		void *function = dlsym(unicode, versioned);
		if (!function) { die("the ICU runtime lacks %s", versioned); }
		return function;
	}
	if (!strncmp(name, "_sqlite3_", 9)) {
		static void *database;
		if (!database) { database = dlopen("libsqlite3.so.0", RTLD_NOW | RTLD_LOCAL); }
		if (!database) { die("the modern prototype needs its SQLite runtime: %s", dlerror()); }
		void *function = dlsym(database, name + 1);
		if (!function) { die("the SQLite runtime lacks %s", name); }
		return function;
	}
	// Darwin and GNU use the same Itanium exception ABI; framework-specific C++ classes still come from the downloaded components.
	if (!strncmp(name, "___cxa_", 7) || !strncmp(name, "__Z", 3) || !strncmp(name, "__Unwind_", 9) || !strcmp(name, "___dynamic_cast") || !strcmp(name, "___gxx_personality_v0")) {
		static void *libcxx;
		if (!libcxx) {
			libcxx = dlopen("libc++.so.1", RTLD_NOW | RTLD_LOCAL);
		}
		if (libcxx) {
			void *function = dlsym(libcxx, name + 1);
			if (function) { return function; }
		}
		static void *runtime;
		if (!runtime) {
			runtime = dlopen("libstdc++.so.6", RTLD_NOW | RTLD_LOCAL);
		}
		if (runtime) {
			void *function = dlsym(runtime, name + 1);
			if (function) {
				return function;
			}
		}
	}
	const char *suffix = strchr(name, '$');
	if (suffix && (size_t)(suffix - name) < 128) {
		char base[128];
		memcpy(base, name, suffix - name);
		base[suffix - name] = 0;
		return lookup_shim(base);
	}
	return NULL;
}

static void *find_export(image *component, const char *name) {
	for (unsigned index = 0; index < component->nsyms; index++) {
		const nlist *symbol = &component->syms[index];
		if (!(symbol->n_type & N_STAB) && (symbol->n_type & N_TYPE) == 0xe && (symbol->n_type & N_EXT) && !strcmp(component->strs + symbol->n_strx, name)) {
			return (void *)(symbol->n_value + component->slide);
		}
	}
	return NULL;
}

static void *modern_symbol(image *component, const char *name) {
	void *result = lookup_shim(name);
	if (result) {
		return result;
	}
	for (int index = 0; index < g_nimages; index++) {
		result = find_export(g_images[index], name);
		if (result) {
			return result;
		}
	}
	(void)component;
	return make_thunk(name);
}

static void require_fixup(const image *component, uint64_t offset, uint64_t length) {
	if (offset > component->fixups_size || length > component->fixups_size - offset) {
		die("truncated chained fixup data in %s", component->path);
	}
}

static void modern_bind_cached(image *component) {
	if (component->slide || !component->dys) {
		die("cached image must retain its original address and indirect symbols");
	}
	const uint32_t *indirect = (const uint32_t *)(component->slice + component->dys->indirectsymoff);
	char binding_path[CFPATH];
	if (snprintf(binding_path, sizeof(binding_path), "%s.bindings", component->path) >= (int)sizeof(binding_path)) {
		die("cached binding path is too long");
	}
	FILE *binding_file = fopen(binding_path, "r");
	if (!binding_file) { die("cached component needs locally generated bindings: %s", binding_path); }
	struct { uint64_t previous, replacement; const char *name; } replacements[1024];
	unsigned count = 0;
	unsigned long long slot_address;
	char symbol_name[1024];
	char line[1200];
	unsigned long long expected_fingerprint;
	if (!fgets(line, sizeof(line), binding_file) || sscanf(line, "# source %llx", &expected_fingerprint) != 1) {
		die("cached bindings have no component fingerprint");
	}
	uint64_t fingerprint = 14695981039346656037ULL;
	size_t file_size = component->slice_size + (size_t)(component->slice - component->file);
	for (size_t index = 0; index < file_size; index++) {
		fingerprint = (fingerprint ^ component->file[index]) * 1099511628211ULL;
	}
	if (fingerprint != expected_fingerprint) { die("cached bindings belong to a different component"); }
	unsigned external_slots = 0;
	while (fgets(line, sizeof(line), binding_file)) {
		int metadata = line[0] == '@';
		if (sscanf(line + metadata, "%llx %1023s", &slot_address, symbol_name) != 2) {
			die("invalid cached binding record");
		}
		char *owned_name = strdup(symbol_name);
		uint64_t replacement = (uintptr_t)modern_symbol(component, owned_name);
		if (metadata) {
			if (count >= 1024) { die("too many cached external symbols"); }
			replacements[count].previous = slot_address;
			replacements[count].replacement = replacement;
			replacements[count].name = owned_name;
			count++;
			continue;
		}
		if (slot_address < component->lo || slot_address > component->hi - 8) {
			die("cached binding slot is outside its reserved address range");
		}
		uintptr_t page = (uintptr_t)slot_address & ~(uintptr_t)4095;
		if (!VirtualAlloc((void *)page, 4096, MEM_COMMIT, PAGE_READWRITE)) {
			die("cannot commit a cached import page");
		}
		*(uint64_t *)(uintptr_t)slot_address = replacement;
		external_slots++;
	}
	if (!feof(binding_file)) { die("invalid cached binding sidecar"); }
	fclose(binding_file);
	for (int section_index = 0; section_index < component->nsects; section_index++) {
		const section *item = &component->sects[section_index];
		unsigned type = item->flags & 0xff;
		if (type != S_NON_LAZY_SYMBOL_PTR && type != S_LAZY_SYMBOL_PTR && strcmp(item->sectname, "__got")) { continue; }
		uint64_t slots = item->size / 8;
		if (item->reserved1 > component->dys->nindirectsyms || slots > component->dys->nindirectsyms - item->reserved1) {
			die("cached indirect symbols exceed their table");
		}
		uint64_t *pointers = (uint64_t *)(item->addr + component->slide);
		for (uint64_t slot = 0; slot < slots; slot++) {
			uint32_t symbol_index = indirect[item->reserved1 + slot];
			if (symbol_index & (INDIRECT_SYMBOL_LOCAL | INDIRECT_SYMBOL_ABS)) { continue; }
			if (symbol_index >= component->nsyms || count >= 1024) { die("invalid cached import"); }
			const char *name = component->strs + component->syms[symbol_index].n_strx;
			uint64_t replacement = (uintptr_t)modern_symbol(component, name);
			replacements[count].previous = pointers[slot];
			replacements[count].replacement = replacement;
			replacements[count].name = name;
			count++;
			pointers[slot] = replacement;
		}
	}
	// Cached C++ RTTI stores imported vtables directly as well as through the GOT.
	for (int section_index = 0; section_index < component->nsects; section_index++) {
		const section *item = &component->sects[section_index];
		if (!strcmp(item->sectname, "__got") || strncmp(item->segname, "__DATA", 6)) { continue; }
		uint64_t *values = (uint64_t *)(item->addr + component->slide);
		for (uint64_t word = 0; word < item->size / 8; word++) {
			for (unsigned index = 0; index < count; index++) {
				if (!replacements[index].previous) { continue; }
				if (values[word] == replacements[index].previous) {
					values[word] = replacements[index].replacement;
					break;
				}
				if (!strncmp(replacements[index].name, "__ZTV", 5) && values[word] == replacements[index].previous + 16) {
					values[word] = replacements[index].replacement + 16;
					break;
				}
			}
		}
	}
	printf("  rebound %u shared-cache imports and %u coalesced slots\n", count, external_slots);
}

static uint64_t modern_uleb(const unsigned char **cursor, const unsigned char *end) {
	uint64_t value = 0;
	unsigned shift = 0;
	unsigned char byte;
	do {
		if (*cursor == end || shift >= 70) {
			die("invalid dyld variable-length integer");
		}
		byte = *(*cursor)++;
		if (shift < 64) {
			value |= (uint64_t)(byte & 0x7f) << shift;
		}
		shift += 7;
	} while (byte & 0x80);
	return value;
}

static void modern_bytecode(image *component, unsigned offset, unsigned size, int binding, int lazy) {
	require_slice(component, offset, size);
	const unsigned char *cursor = component->slice + offset;
	const unsigned char *end = cursor + size;
	unsigned segment = 0;
	uint64_t displacement = 0;
	int64_t addend = 0;
	const char *name = NULL;
	unsigned type = 1;
	unsigned flags = 0;
	while (cursor < end) {
		unsigned byte = *cursor++;
		unsigned operation = byte & 0xf0;
		unsigned immediate = byte & 15;
		uint64_t count = 0;
		uint64_t skip = 0;
		if (!operation) {
			if (!lazy) {
				return;
			}
			name = NULL;
			addend = 0;
			continue;
		}
		if (binding) {
			switch (operation) {
			case 0x10: case 0x30: continue;
			case 0x20: modern_uleb(&cursor, end); continue;
			case 0x40:
				name = (const char *)cursor;
				flags = immediate;
				while (cursor < end && *cursor) { cursor++; }
				if (cursor == end) { die("unterminated dyld symbol"); }
				cursor++;
				continue;
			case 0x50: type = immediate; continue;
			case 0x60: {
				const unsigned char *start = cursor;
				uint64_t encoded = modern_uleb(&cursor, end);
				unsigned bits = (cursor - start) * 7;
				if (bits < 64 && cursor[-1] & 0x40) { encoded |= UINT64_MAX << bits; }
				addend = (int64_t)encoded;
				continue;
			}
			case 0x70: segment = immediate; displacement = modern_uleb(&cursor, end); continue;
			case 0x80: displacement += modern_uleb(&cursor, end); continue;
			case 0x90: count = 1; break;
			case 0xa0: count = 1; skip = modern_uleb(&cursor, end); break;
			case 0xb0: count = 1; skip = immediate * 8; break;
			case 0xc0: count = modern_uleb(&cursor, end); skip = modern_uleb(&cursor, end); break;
			default: die("unsupported 64-bit dyld bind opcode 0x%x", operation);
			}
		}
		else {
			switch (operation) {
			case 0x10: type = immediate; continue;
			case 0x20: segment = immediate; displacement = modern_uleb(&cursor, end); continue;
			case 0x30: displacement += modern_uleb(&cursor, end); continue;
			case 0x40: displacement += immediate * 8; continue;
			case 0x50: count = immediate; break;
			case 0x60: count = modern_uleb(&cursor, end); break;
			case 0x70: count = 1; skip = modern_uleb(&cursor, end); break;
			case 0x80: count = modern_uleb(&cursor, end); skip = modern_uleb(&cursor, end); break;
			default: die("unsupported 64-bit dyld rebase opcode 0x%x", operation);
			}
		}
		if (type != 1 || segment >= (unsigned)component->nsegs) {
			die("unsupported dyld fixup type or segment");
		}
		for (uint64_t index = 0; index < count; index++) {
			uint64_t address = component->segaddr[segment] + displacement;
			if (address < component->lo || address > component->hi || component->hi - address < 8) {
				die("dyld fixup is outside its image");
			}
			uint64_t *slot = (uint64_t *)(address + component->slide);
			if (binding) {
				if (!name) { die("dyld bind has no symbol"); }
				void *function = NULL;
				if (flags & 1) {
					function = lookup_shim(name);
					for (int image_index = 0; !function && image_index < g_nimages; image_index++) {
						function = find_export(g_images[image_index], name);
					}
				}
				else { function = modern_symbol(component, name); }
				*slot = (uintptr_t)function + addend;
			}
			else { *slot += component->slide; }
			displacement += 8 + skip;
		}
	}
}

static void apply_binds(image *component, image *dependency) {
	(void)dependency;
	if (component->info) {
		const dyld_info_command *information = component->info;
		modern_bytecode(component, information->bind_off, information->bind_size, 1, 0);
		modern_bytecode(component, information->weak_off, information->weak_size, 1, 0);
		modern_bytecode(component, information->lazy_off, information->lazy_size, 1, 1);
		return;
	}
	if (!component->fixups_size) {
		if (component->lo > UINT32_MAX) {
			modern_bind_cached(component);
			return;
		}
		die("component has no supported chained fixups: %s", component->path);
	}
	unsigned char *fixups = component->slice + component->fixups_offset;
	require_fixup(component, 0, 28);
	uint32_t *header = (uint32_t *)fixups;
	if (header[0] != 0 || header[6] != 0 || header[5] < 1 || header[5] > 3) {
		die("unsupported chained fixup format");
	}
	uint32_t starts_offset = header[1];
	uint32_t imports_offset = header[2];
	uint32_t symbols_offset = header[3];
	uint32_t imports_count = header[4];
	uint32_t import_stride = header[5] == 3 ? 16 : header[5] == 2 ? 8 : 4;
	require_fixup(component, imports_offset, (uint64_t)imports_count * import_stride);
	require_fixup(component, symbols_offset, 0);
	require_fixup(component, starts_offset, 4);
	uint32_t *starts = (uint32_t *)(fixups + starts_offset);
	uint32_t segment_count = starts[0];
	require_fixup(component, starts_offset + 4, (uint64_t)segment_count * 4);
	unsigned bound = 0;
	unsigned rebased = 0;
	for (uint32_t index = 0; index < segment_count; index++) {
		if (!starts[index + 1]) {
			continue;
		}
		uint64_t segment_offset = (uint64_t)starts_offset + starts[index + 1];
		require_fixup(component, segment_offset, 22);
		unsigned char *segment = fixups + segment_offset;
		uint32_t size = *(uint32_t *)segment;
		uint16_t page_size = *(uint16_t *)(segment + 4);
		uint16_t pointer_format = *(uint16_t *)(segment + 6);
		uint64_t image_offset = *(uint64_t *)(segment + 8);
		uint16_t page_count = *(uint16_t *)(segment + 20);
		require_fixup(component, segment_offset, size);
		if (size < 22 + (uint32_t)page_count * 2 || !page_size || (pointer_format != MODERN_POINTER_64 && pointer_format != MODERN_POINTER_64_OFFSET)) {
			die("unsupported chained pointer layout %u", pointer_format);
		}
		for (uint32_t page = 0; page < page_count; page++) {
			uint16_t page_start = *(uint16_t *)(segment + 22 + page * 2);
			if (page_start == MODERN_PAGE_NONE) {
				continue;
			}
			if (page_start & 0x8000) {
				die("multiple chained fixup starts on a page are not implemented");
			}
			uint64_t location = image_offset + (uint64_t)page * page_size + page_start;
			for (;;) {
				if (location > component->hi - component->lo || 8 > component->hi - component->lo - location) {
					die("chained pointer outside mapped image");
				}
				uint64_t *slot = (uint64_t *)(component->lo + component->slide + location);
				uint64_t encoded = *slot;
				uint64_t next = (encoded >> 51) & 0xfff;
				if (encoded >> 63) {
					uint32_t ordinal = encoded & 0xffffff;
					if (ordinal >= imports_count) {
						die("invalid chained import ordinal");
					}
					unsigned char *entry = fixups + imports_offset + ordinal * import_stride;
					uint64_t entry_value = header[5] == 3 ? *(uint64_t *)entry : *(uint32_t *)entry;
					uint64_t name_offset = entry_value >> (header[5] == 3 ? 32 : 9);
					uint64_t name_location = (uint64_t)symbols_offset + name_offset;
					require_fixup(component, name_location, 1);
					const char *name = (char *)fixups + name_location;
					if (!memchr(name, 0, component->fixups_size - name_location)) {
						die("unterminated chained import name");
					}
					int64_t addend = (int8_t)(encoded >> 24);
					if (header[5] == 2) {
						addend += *(int32_t *)(entry + 4);
					}
					else if (header[5] == 3) {
						addend += *(int64_t *)(entry + 8);
					}
					*slot = (uintptr_t)modern_symbol(component, name) + addend;
					bound++;
				}
				else {
					uint64_t target = encoded & 0xfffffffffULL;
					uint64_t high = ((encoded >> 36) & 0xff) << 56;
					*slot = pointer_format == MODERN_POINTER_64_OFFSET ? component->lo + component->slide + target + high : component->slide + target + high;
					rebased++;
				}
				if (!next) {
					break;
				}
				location += next * 4;
			}
		}
	}
	if (g_verbose) {
		printf("  modern fixups: %u rebased, %u bound\n", rebased, bound);
	}
}

static void apply_rebases(image *component) {
	if (component->info) {
		modern_bytecode(component, component->info->rebase_off, component->info->rebase_size, 0, 0);
	}
}

static void resolve(image *component, image *dependency) {
	apply_binds(component, dependency);
}

static void run_initializers(image *component) {
	for (int index = 0; index < component->nsects; index++) {
		section *item = &component->sects[index];
		if ((item->flags & 0xff) == S_MOD_INIT_FUNC) {
			uint64_t *functions = (uint64_t *)(item->addr + component->slide);
			for (uint64_t function_index = 0; function_index < item->size / 8; function_index++) {
				((void (*)(void))(uintptr_t)functions[function_index])();
			}
		}
	}
}

static void load(image *component, const char *path) {
	memset(component, 0, sizeof(*component));
	component->path = strdup(path);
	size_t length = 0;
	component->file = read_file(path, &length);
	component->slice = find_i386(component->file, length);
	component->slice_size = length - (size_t)(component->slice - component->file);
	map_image(component);
	apply_rebases(component);
}

static int dyld_check(const char *path) {
	image component;
	load(&component, path);
	printf("64-bit component: %u symbols; %u bytes of chained fixups\n", component.nsyms, component.fixups_size);
	return 0;
}
