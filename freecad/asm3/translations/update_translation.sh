#!/usr/bin/env bash

# --------------------------------------------------------------------------------------------------
#
# Create, update and release translation files.
#
# Supported locales on FreeCAD <2024-03-13, FreeCADGui.supportedLocales(), total=43>:
# 	{'English': 'en', 'Afrikaans': 'af', 'Arabic': 'ar', 'Basque': 'eu', 'Belarusian': 'be',
# 	'Bulgarian': 'bg', 'Catalan': 'ca', 'Chinese Simplified': 'zh-CN',
# 	'Chinese Traditional': 'zh-TW', 'Croatian': 'hr', 'Czech': 'cs', 'Dutch': 'nl',
# 	'Filipino': 'fil', 'Finnish': 'fi', 'French': 'fr', 'Galician': 'gl', 'Georgian': 'ka',
# 	'German': 'de', 'Greek': 'el', 'Hungarian': 'hu', 'Indonesian': 'id', 'Italian': 'it',
# 	'Japanese': 'ja', 'Kabyle': 'kab', 'Korean': 'ko', 'Lithuanian': 'lt', 'Norwegian': 'no',
# 	'Polish': 'pl', 'Portuguese': 'pt-PT', 'Portuguese, Brazilian': 'pt-BR', 'Romanian': 'ro',
# 	'Russian': 'ru', 'Serbian': 'sr', 'Serbian, Latin': 'sr-CS', 'Slovak': 'sk',
# 	'Slovenian': 'sl', 'Spanish': 'es-ES', 'Spanish, Argentina': 'es-AR', 'Swedish': 'sv-SE',
# 	'Turkish': 'tr', 'Ukrainian': 'uk', 'Valencian': 'val-ES', 'Vietnamese': 'vi'}
#
# NOTE: PREPARATION
# - Install Qt tools
# 	Debian-based (e.g., Ubuntu): $ sudo apt-get install qttools5-dev-tools pyqt6-dev-tools
# 	Fedora-based: $ sudo dnf install qt6-linguist qt6-devel
# 	Arch-based: $ sudo pacman -S qt6-tools python-pyqt6
# - Make the script executable
# 	$ chmod +x update_translation.sh
# - The script has to be executed within the `freecad/freegrid/resources/translations` directory.
# 	Executing the script with no flags invokes the help.
# 	$ ./update_translation.sh
#
# NOTE: WORKFLOW TRANSLATOR (LOCAL)
# - Execute the script passing the `-u` flag plus locale code as argument
# 	Only update the file(s) you're translating!
# 	$ ./update_translation.sh -u es-ES
# - Do the translation via Qt Linguist and use `File>Release`
# - If releasing with the script execute it passing the `-r` flag
# 	plus locale code as argument
# 	$ ./update_translation.sh -r es-ES
#
# NOTE: WORKFLOW MAINTAINER (CROWDIN)
# - Execute the script passing the '-U' flag
# 	$ ./update_translation.sh -U
# - Upload the updated file to Crowdin and wait for translators do their thing ;-)
# - Once done, download the translated files, copy them to `freecad/freegrid/resources/translations`
# 	and release all the files to update the changes
# 	$ ./update_translation.sh -R
#
# The usage of `pylupdate6` is preferred over 'pylupdate5' when extracting text strings from
# 	Python files. Also using `lupdate` from Qt6 is possible.
#
# --------------------------------------------------------------------------------------------------

supported_locales=(
	"en" "af" "ar" "eu" "be" "bg" "ca" "zh-CN" "zh-TW" "hr"
	"cs" "nl" "fil" "fi" "fr" "gl" "ka" "de" "el" "hu"
	"id" "it" "ja" "kab" "ko" "lt" "no" "pl" "pt-PT" "pt-BR"
	"ro" "ru" "sr" "sr-CS" "sk" "sl" "es-ES" "es-AR" "sv-SE" "tr"
	"uk" "val-ES" "vi"
)

is_locale_supported() {
	local locale="$1"
	for supported_locale in "${supported_locales[@]}"; do
		if [[ "$supported_locale" == "$locale" ]]; then
			return 0
		fi
	done
	return 1
}

get_strings() {
	# Get translatable strings from Qt Designer files
	# lupdate ../ui/*.ui -ts uifiles.ts -no-obsolete
	# Get translatable strings from Python file(s)
	# pylupdate5 ../../*.py -ts pyfiles.ts -verbose
	pylupdate6 ../*.py -ts pyfiles.ts -no-obsolete
	# Join strings from Qt Designer and Python files into a single temp file
	lconvert -i pyfiles.ts -o _${WB}.ts -sort-contexts -no-obsolete
}

update_locale() {
	local locale="$1"
	local u=${locale:+_} # Conditional underscore

	# NOTE: Execute the right commands depending on:
	# - if the file already exists and
	# - if it's a locale file or the main, agnostic one
	if [ ! -f "${WB}${u}${locale}.ts" ]; then
		echo -e "\033[1;34m\n\t<<< Creating '${WB}${u}${locale}.ts' file >>>\n\033[m"
		get_strings
		if [ "$locale" == "" ]; then
			lconvert -i _${WB}.ts -o ${WB}.ts
		else
			lconvert -source-language en -target-language "${locale//-/_}" \
				-i _${WB}.ts -o ${WB}_${locale}.ts
		fi
	else
		echo -e "\033[1;34m\n\t<<< Updating '${WB}${u}${locale}.ts' file >>>\n\033[m"
		get_strings
		if [ "$locale" == "" ]; then
			lconvert -i _${WB}.ts ${WB}.ts -o ${WB}.ts
		else
			lconvert -source-language en -target-language "${locale//-/_}" \
				-i _${WB}.ts ${WB}_${locale}.ts -o ${WB}_${locale}.ts
		fi
	fi

	# Delete files that are no longer needed
	rm -f pyfiles.ts _${WB}.ts
}

release_locale() {
	# Release locale (creation of *.qm file from *.ts file)
	local locale="$1"
	lrelease ${WB}_${locale}.ts
}

help() {
	echo -e "\nDescription:"
	echo -e "\tCreate, update and release translation files."
	echo -e "\nUsage:"
	echo -e "\t./update_translation.sh [-R] [-U] [-r <locale>] [-u <locale>]"
	echo -e "\nFlags:"
	echo -e "  -R\n\tRelease all locales"
	echo -e "  -U\n\tUpdate main translation file (locale agnostic)"
	echo -e "  -r <locale>\n\tRelease the specified locale"
	echo -e "  -u <locale>\n\tUpdate strings for the specified locale"
}

# Main function ------------------------------------------------------------------------------------

WB="asm3"

if [ $# -eq 0 ]; then
	help
elif [ $# -eq 1 ]; then
	if [ "$1" == "-R" ]; then
		find . -type f -name '*_*.ts' | while IFS= read -r file; do
			# Release all locales
			lrelease $file
			echo
		done
	elif [ "$1" == "-U" ]; then
		# Update main file (agnostic)
		update_locale
	else
		help
	fi
elif [ $# -eq 2 ]; then
	LOCALE="$2"
	if is_locale_supported "$LOCALE"; then
		if [ "$1" == "-r" ]; then
			# Release locale
			release_locale "$LOCALE"
		elif [ "$1" == "-u" ]; then
			# Update main & locale files
			update_locale
			update_locale "$LOCALE"
		fi
	else
		echo "Verify your language code. Case sensitive."
		echo "If it's correct ask a maintainer to add support for your language on FreeCAD."
	fi
else
	help
fi
