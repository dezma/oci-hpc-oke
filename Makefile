.PHONY: test payload orm

test:
	./provisioning/validate.sh

payload:
	./provisioning/build-operator-payload.sh

orm:
	./provisioning/build-orm.sh
