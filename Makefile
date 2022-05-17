# See https://stackoverflow.com/questions/53382383/makefile-cant-use-conda-activate
SHELL=/bin/bash
CONDA_ACTIVATE=source $$(conda info --base)/etc/profile.d/conda.sh ; conda activate ; conda activate
define lower 
$(shell echo $(1) | tr A-Z a-z)
endef

EXPERIMENTS=gs://vcm-ml-experiments/spencerc
CLIMATES = minus-4K unperturbed plus-4K plus-8K
SEEDS = 0 1 2 3

# Preparation steps
C384_SFC_DATA_ROOT=$(EXPERIMENTS)/2022-01-19-C384-sfc_data-initial-conditions
C384_AREA=$(C384_SFC_DATA_ROOT)/area/area
PATCHED_RESTART_FILE_DESTINATION=$(EXPERIMENTS)/2022-01-19-C48-snoalb-patched-restart-files
C48_REFERENCE_ROOT=gs://vcm-ml-raw-flexible-retention/2021-01-04-1-year-C384-FV3GFS-simulations
NUDGED_RUN_START_DATE=20170801.010000
PROGNOSTIC_RUN_START_DATE=20180801.000000

# Nudged runs
PRESCRIBER_REFERENCE_ROOT=gs://vcm-ml-intermediate/2021-04-30-nudge-to-25-km-prescriber-datasets

# ML training
TRAINING_DATA=gs://vcm-ml-experiments/spencerc/2022-03-12/n2f-25km-tapered-25-snoalb-nudging-tendencies-and-fluxes.zarr
TRAIN_ROOT=gs://vcm-ml-experiments/spencerc/2022-03-12-nudge-to-25-km-ml-models
FLUXES_RF_BASE=$(TRAIN_ROOT)/fluxes-rf-transmissivity-snoalb
FLUXES_RF_DERIVED=$(TRAIN_ROOT)/fluxes-rf-transmissivity-snoalb-derived
TQ_NN=$(TRAIN_ROOT)/tq-nn-snoalb-tapered-clipped-25

# Figures
FIGURES = figure-01 figure-02 figure-03 figure-04 figure-05 figure-06 figure-07 figure-08 figure-09 figure-10 figure-11 figure-12 figure-13 table-02


create_environment:
	make -C fv3net-ml-corrected update_submodules && \
		make -C fv3net-ml-corrected create_environment && \
		( $(CONDA_ACTIVATE) fv3net ; pip install faceted==0.2.1 ; pip install nc-time-axis==1.4.1 ; pip install proplot==0.9.5 ; pip install seaborn==0.11.2 ; pip install xhistogram==0.3.1 )


# Patch the maximum snow albedo in restart files to address a coarse-graining error that
# enters the initial conditions.
patch_snoalb: $(addprefix patch_snoalb_in_initial_conditions_, $(CLIMATES))
patch_snoalb_in_initial_conditions_%:
	python workflows/scripts/patch_snoalb.py \
		$(C384_SFC_DATA_ROOT)/$*/sfc_data \
		$(C384_AREA) \
		$(C48_REFERENCE_ROOT)/$*/C384-to-C48-restart-files \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		$(NUDGED_RUN_START_DATE) $(PROGNOSTIC_RUN_START_DATE)


# Nudged runs
generate_prescriber_reference: $(addprefix generate_prescriber_reference_, $(CLIMATES))
generate_prescriber_reference_%:
	python workflows/scripts/generate_prescriber_reference_dataset.py \
		$(C48_REFERENCE_ROOT)/$*/C384-to-C48-diagnostics/gfsphysics_15min_coarse.zarr \
		$(PRESCRIBER_REFERENCE_ROOT)/$*/prescriber_reference.zarr


nudged_runs: $(addprefix nudged_run_, $(CLIMATES))
nudged_run_%: deploy_nudged_or_baseline
	workflows/scripts/run-nudged.sh \
		$(call lower,$*)-snoalb \
		$(C48_REFERENCE_ROOT)/$*/C384-to-C48-restart-files \
		workflows/nudged-runs/$(call lower,$*).yaml


# Baseline runs
baseline_runs: $(addprefix baseline_run_, $(CLIMATES))
baseline_run_%: deploy_nudged_or_baseline
	workflows/scripts/run-baseline.sh \
		$(call lower,$*)-snoalb \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		workflows/baseline-runs/$(call lower,$*).yaml


# ML training
training_dataset:
	python ./notebooks/generate_training_dataset.py $(TRAINING_DATA)


train_base_radiative_flux_model: deploy_ml_corrected
	./workflows/scripts/train-rf.sh \
		workflows/ml-training/fluxes-rf-base.yaml \
		workflows/ml-training/training-data-config.yaml  \
		$(FLUXES_RF_BASE)


create_derived_radiative_flux_model: deploy_ml_corrected
	./workflows/scripts/create-derived-model.sh \
		$(abspath workflows/ml-training/fluxes-rf-derived.yaml) \
		$(FLUXES_RF_DERIVED)


train_nudging_tendency_nn_seed_%: deploy_ml_corrected
	./workflows/scripts/train-nn.sh \
		workflows/ml-training/tq-nn-training-config.yaml \
		workflows/ml-training/training-data-config.yaml  \
		$* \
		$(TQ_NN)


# ML-corrected runs
ml_corrected_runs: $(addprefix ml_corrected_run_, $(CLIMATES))
ml_corrected_run_%: deploy_ml_corrected
	./workflows/scripts/run-ml-corrected.sh \
		ml-corrected-v3-$(call lower,$*) \
		$(PATCHED_RESTART_FILE_DESTINATION)/$* \
		workflows/ml-corrected-runs/$(call lower,$*).yaml \
		$(TQ_NN) \
		"0 1 2 3" \
		46 \
		$(FLUX_RF_DERIVED)


extend_ml_corrected_seed_2_runs: deploy_ml_corrected
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-03-29/n2f-25km-ml-corrected-v3-minus-4k-seed-2/fv3gfs_run 146
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-03-13/n2f-25km-ml-corrected-v3-unperturbed-seed-2/fv3gfs_run 146
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-03-29/n2f-25km-ml-corrected-v3-plus-4k-seed-2/fv3gfs_run 146
	./workflows/scripts/restart.sh gs://vcm-ml-experiments/spencerc/2022-03-29/n2f-25km-ml-corrected-v3-plus-8k-seed-2/fv3gfs_run 146


# Post-processing and figure creation
post_process_simulations:
	python post_processing.py
	python metrics.py
	python diurnal_cycle.py
	python imerg_diurnal_cycle.py


create_figures: $(addprefix execute_notebook_, $(FIGURES))


execute_notebook_%:
	jupyter nbconvert --to notebook --execute notebooks/$**.ipynb


# Workflow configuration
kustomize:
	./install_kustomize.sh 3.10.0


deploy_notebooks: kustomize
	./kustomize build notebooks/ | kubectl apply -f -


deploy_nudged_or_baseline: kustomize
	./kustomize build fv3net-nudged-or-baseline | kubectl apply -f -


deploy_ml_corrected: kustomize
	./kustomize build fv3net-ml-corrected | kubectl apply -f -
