# Narzędzia w wersjach z mise.toml mają pierwszeństwo przed systemowymi,
# także gdy mise nie jest aktywowane w powłoce.
export PATH := $(shell mise bin-paths 2>/dev/null | tr '\n' ':')$(PATH)

.PHONY: doctor

# Sprawdza narzędzia z mise.toml, dostęp do Dockera bez sudo, pamięć Dockera i limity inotify.
doctor:
	@bash scripts/doctor.sh
