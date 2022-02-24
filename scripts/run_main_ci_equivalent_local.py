"""script to run a rough equivalent of the github actions workflow 'collection_main.yaml' locally"""
import json
import shutil
import subprocess
from pathlib import Path
from pprint import pprint

import typer

from dynamic_validation import main as dynamic_validation_script
from generate_collection_rdf import main as generate_collection_rdf_script
from prepare_to_deploy import main as prepare_to_deploy_script
from static_validation import main as static_validation_script
from update_external_resources import main as update_external_resources_script
from update_partner_resources import main as update_partner_resources_script
from update_rdfs import main as update_rdfs_script
from utils import iterate_over_gh_matrix


def fake_deploy(dist: Path, deploy_to: Path):
    if dist.exists():
        shutil.copytree(str(dist), str(deploy_to), dirs_exist_ok=True)
        shutil.rmtree(str(dist))


def end_of_step(always_continue: bool):
    if not always_continue and input("Continue?([y]/n)").lower().startswith("n"):
        raise RuntimeError("abort")


def main(
    collection: Path = Path(__file__).parent / "../collection",
    last_collection: Path = Path(__file__).parent / "../last_ci_run/collection",
    gh_pages: Path = Path(__file__).parent / "../gh-pages",
    dist: Path = Path(__file__).parent / "../dist",
    artifacts: Path = Path(__file__).parent / "../artifacts",
    partner_test_summaries: Path = Path(__file__).parent / "../partner_test_summaries",
    rdf_template_path: Path = Path(__file__).parent / "../collection_rdf_template.yaml",
    current_collection_format: str = "0.2.2",
    always_continue: bool = True,
):
    # local setup
    if not partner_test_summaries.exists():
        partner_test_summaries.mkdir(parents=True)
        # todo: download partner_test_summaries

    if not gh_pages.exists():
        subprocess.run(["git", "worktree", "prune"], check=True)
        subprocess.run(["git", "worktree", "add", "--detach", str(gh_pages), "gh-pages"], check=True)

    if not last_collection.parent.exists():
        subprocess.run(["git", "worktree", "prune"], check=True)
        subprocess.run(["git", "worktree", "add", "--detach", str(last_collection.parent), "last_ci_run"], check=True)

    if dist.exists():
        print(f"rm dist {dist}")
        shutil.rmtree(str(dist))

    if artifacts.exists():
        print(f"rm artifacts {artifacts}")
        shutil.rmtree(str(artifacts))

    ###################################
    # update resources (resource infos)
    ###################################
    updates = update_external_resources_script(collection=collection)
    print("would open auto-update PRs with:")
    pprint(updates)

    fake_deploy(dist, collection)  # in CI done via PRs

    update_partner_resources_script(
        dist=dist,
        gh_pages=gh_pages,
        rdf_template_path=rdf_template_path,
        current_collection_format=current_collection_format,
    )
    fake_deploy(dist, gh_pages)

    end_of_step(always_continue)
    #################################
    # update rdfs (resource versions)
    #################################
    pending = update_rdfs_script(
        dist=dist / "updated_rdfs",
        collection=collection,
        last_collection=last_collection,
        gh_pages=gh_pages,
    )

    print("\npending (updated):")
    pprint(pending)

    end_of_step(always_continue)
    ############################
    # validate/static-validation
    ############################
    # perform static validation for pending resources
    static_out = static_validation_script(
        dist=artifacts / "static_validation_artifact",
        pending_matrix=json.dumps(
            dict(
                include=pending["pending_matrix"].get("include", [])
                + pending["pending_matrix_bioimageio"].get("include", [])
            )
        ),
        rdf_dirs=[dist / "updated_rdfs/rdfs", gh_pages / "rdfs"],
    )
    print("\nstatic validation:")
    pprint(static_out)

    end_of_step(always_continue)
    #############################
    # validate/dynamic-validation
    #############################
    for matrix in iterate_over_gh_matrix(static_out["dynamic_test_cases"]):
        print(
            f"\ndynamic validation (r: {matrix['resource_id']}, v: {matrix['version_id']}, w: {matrix['weight_format']}):"
        )
        dynamic_validation_script(
            dist=artifacts / "dynamic_validation_artifacts",
            resource_id=matrix["resource_id"],
            version_id=matrix["version_id"],
            rdf_dirs=[artifacts / "static_validation_artifact"],
            weight_format=matrix["weight_format"],
        )

    end_of_step(always_continue)
    #################
    # validate/deploy
    #################
    prepare_to_deploy_script(
        dist=dist,
        collection=collection,
        gh_pages=gh_pages,
        artifact_dir=artifacts,
        partner_test_summaries=partner_test_summaries,
    )

    fake_deploy(dist, gh_pages)

    end_of_step(always_continue)
    ##################
    # build-collection
    ##################
    generate_collection_rdf_script(collection=collection, dist=dist)

    fake_deploy(dist, gh_pages)
    if pending["retrigger"]:
        print("incomplete collection update. needs additional run(s).")


if __name__ == "__main__":
    typer.run(main)
