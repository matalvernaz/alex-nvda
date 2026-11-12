// Decode local cache instructions for setup without requiring a Python extension or executing the component.
#include <capstone/capstone.h>

static int modern_scan_cache(const char *path, const char *output_path) {
	size_t length;
	unsigned char *file = read_file(path, &length);
	unsigned char *slice = find_i386(file, length);
	image component;
	memset(&component, 0, sizeof component);
	component.path = path;
	component.slice = slice;
	component.slice_size = length - (size_t)(slice - file);
	mach_header *header = (mach_header *)slice;
	require_slice(&component, sizeof(*header), header->sizeofcmds);
	csh decoder;
	if (cs_open(CS_ARCH_X86, CS_MODE_64, &decoder) != CS_ERR_OK) { die("cannot start the setup instruction decoder"); }
	cs_option(decoder, CS_OPT_DETAIL, CS_OPT_ON);
	cs_option(decoder, CS_OPT_SKIPDATA, CS_OPT_ON);
	cs_insn *instruction = cs_malloc(decoder);
	FILE *output = fopen(output_path, "w");
	if (!instruction || !output) { die("cannot create the local setup reference list"); }
	fputc('[', output);
	int first = 1;
	size_t command_offset = sizeof(*header);
	for (unsigned command_index = 0; command_index < header->ncmds; command_index++) {
		require_slice(&component, command_offset, sizeof(load_command));
		load_command *command = (load_command *)(slice + command_offset);
		if (command->cmdsize < sizeof(load_command)) { die("invalid setup component command"); }
		require_slice(&component, command_offset, command->cmdsize);
		if (command->cmd == LC_SEGMENT) {
			if (command->cmdsize < sizeof(segment_command)) { die("invalid setup segment command"); }
			segment_command *segment = (segment_command *)command;
			if (segment->nsects > (command->cmdsize - sizeof(*segment)) / sizeof(section)) { die("invalid setup section count"); }
			section *sections = (section *)(segment + 1);
			for (unsigned section_index = 0; section_index < segment->nsects; section_index++) {
				section *item = &sections[section_index];
				if (strcmp(item->sectname, "__text") && strcmp(item->sectname, "__stubs")) { continue; }
				require_slice(&component, item->offset, item->size);
				const uint8_t *code = slice + item->offset;
				size_t remaining = item->size;
				uint64_t address = item->addr;
				while (cs_disasm_iter(decoder, &code, &remaining, &address, instruction)) {
					if (!instruction->id || !instruction->detail) { continue; }
					cs_x86 *details = &instruction->detail->x86;
					for (unsigned operand_index = 0; operand_index < details->op_count; operand_index++) {
						cs_x86_op *operand = &details->operands[operand_index];
						if (operand->type != X86_OP_MEM || operand->mem.base != X86_REG_RIP) { continue; }
						uint64_t target = instruction->address + instruction->size + operand->mem.disp;
						fprintf(output, "%s%llu", first ? "" : ",", (unsigned long long)target);
						first = 0;
					}
				}
			}
		}
		command_offset += command->cmdsize;
	}
	fputs("]\n", output);
	if (fclose(output)) { die("could not finish the local setup reference list"); }
	cs_free(instruction, 1);
	cs_close(&decoder);
	free(file);
	return 0;
}
