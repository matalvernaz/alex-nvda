// Render through the installed modern MacinTalk engine to provide a reference for the portable implementation.
#include <ApplicationServices/ApplicationServices.h>
#include <CoreFoundation/CoreFoundation.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef int (*OpenChannel)(void **);
typedef int (*CloseChannel)(void *);
typedef int (*UseVoice)(void *, const VoiceSpec *, CFBundleRef);
typedef int (*SetProperty)(void *, CFStringRef, CFTypeRef);
typedef int (*CopyProperty)(void *, CFStringRef, CFTypeRef *);
typedef int (*SpeakCFStringEntry)(void *, CFStringRef, CFDictionaryRef);

static CFURLRef file_url(const char *path, Boolean directory) {
	return CFURLCreateFromFileSystemRepresentation(NULL, (const UInt8 *)path, strlen(path), directory);
}

static int busy_value(CFTypeRef value) {
	if (!value) {
		return -1;
	}
	if (CFGetTypeID(value) == CFBooleanGetTypeID()) {
		return CFBooleanGetValue((CFBooleanRef)value);
	}
	if (CFGetTypeID(value) == CFNumberGetTypeID()) {
		int number = 0;
		CFNumberGetValue((CFNumberRef)value, kCFNumberIntType, &number);
		return number != 0;
	}
	return -1;
}

int main(int argc, char **argv) {
	if (argc != 6) {
		fprintf(stderr, "usage: native_reference ENGINE_BUNDLE VOICE_BUNDLE OUTPUT.wav RATE TEXT\n");
		return 2;
	}
	CFURLRef engine_url = file_url(argv[1], true);
	CFURLRef voice_url = file_url(argv[2], true);
	CFURLRef output_url = file_url(argv[3], false);
	CFBundleRef engine = CFBundleCreate(NULL, engine_url);
	CFBundleRef voice = CFBundleCreate(NULL, voice_url);
	CFErrorRef load_error = NULL;
	if (!engine || !voice || !CFBundleLoadExecutableAndReturnError(engine, &load_error)) {
		fprintf(stderr, "Could not load the system engine or the supplied voice bundle (engine %p, voice %p).\n", (void *)engine, (void *)voice);
		if (load_error) {
			CFShow(load_error);
		}
		return 1;
	}
	OpenChannel open_channel = (OpenChannel)CFBundleGetFunctionPointerForName(engine, CFSTR("SEOpenSpeechChannel"));
	CloseChannel close_channel = (CloseChannel)CFBundleGetFunctionPointerForName(engine, CFSTR("SECloseSpeechChannel"));
	UseVoice use_voice = (UseVoice)CFBundleGetFunctionPointerForName(engine, CFSTR("SEUseVoice"));
	SetProperty set_property = (SetProperty)CFBundleGetFunctionPointerForName(engine, CFSTR("SESetSpeechProperty"));
	CopyProperty copy_property = (CopyProperty)CFBundleGetFunctionPointerForName(engine, CFSTR("SECopySpeechProperty"));
	SpeakCFStringEntry speak = (SpeakCFStringEntry)CFBundleGetFunctionPointerForName(engine, CFSTR("SESpeakCFString"));
	if (!open_channel || !close_channel || !use_voice || !set_property || !copy_property || !speak) {
		fprintf(stderr, "A required speech entry point is missing.\n");
		return 1;
	}
	void *channel = NULL;
	int error = open_channel(&channel);
	fprintf(stderr, "open channel: %d\n", error);
	if (error || !channel) {
		return 1;
	}
	VoiceSpec specification = { .creator = 0x6d656f77, .id = 201 };
	error = use_voice(channel, &specification, voice);
	fprintf(stderr, "use supplied Alex bundle: %d\n", error);
	if (error) {
		return 1;
	}
	// Refuse to speak unless output has been redirected, so the reference test cannot talk over the Mac's user.
	error = set_property(channel, kSpeechOutputToFileURLProperty, output_url);
	fprintf(stderr, "redirect output to file: %d\n", error);
	if (error) {
		return 1;
	}
	if (getenv("NATIVE_REFERENCE_OFFLINE")) {
		CFStringRef *offline_key = (CFStringRef *)dlsym(RTLD_DEFAULT, "kSpeechOfflineModeProperty");
		error = set_property(channel, offline_key ? *offline_key : CFSTR("offl"), kCFBooleanTrue);
		fprintf(stderr, "offline rendering: %d\n", error);
	}
	double rate = strtod(argv[4], NULL);
	CFNumberRef rate_value = CFNumberCreate(NULL, kCFNumberDoubleType, &rate);
	error = set_property(channel, kSpeechRateProperty, rate_value);
	fprintf(stderr, "set rate: %d\n", error);
	if (error) {
		return 1;
	}
	CFStringRef text = CFStringCreateWithCString(NULL, argv[5], kCFStringEncodingUTF8);
	error = speak(channel, text, NULL);
	fprintf(stderr, "speak: %d\n", error);
	if (error) {
		return 1;
	}
	int completed = 0;
	for (int tick = 0; tick < 1500; tick++) {
		CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.01, false);
		CFTypeRef status = NULL;
		error = copy_property(channel, kSpeechStatusProperty, &status);
		if (tick == 0 || tick == 100 || tick == 1499) {
			fprintf(stderr, "status at tick %d: %d\n", tick, error);
			if (status) {
				CFShow(status);
			}
		}
		if (!error && status && CFGetTypeID(status) == CFDictionaryGetTypeID()) {
			CFTypeRef busy = CFDictionaryGetValue((CFDictionaryRef)status, kSpeechStatusOutputBusy);
			int active = busy_value(busy);
			if (active == 0) {
				completed = 1;
				CFRelease(status);
				break;
			}
		}
		if (status) {
			CFRelease(status);
		}
	}
	error = close_channel(channel);
	fprintf(stderr, "close channel: %d; completed: %d\n", error, completed);
	return completed && !error ? 0 : 1;
}
